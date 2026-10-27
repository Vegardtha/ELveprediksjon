"""Prediksjon: siste døgn- og timesvannføring (HydAPI), observert vær/snø/HBV-tilstand (GTS) og
værprognose (MET Nordic via Open-Meteo) → p10/p50/p90 per dag.

p10/p90 justeres med konforme tillegg fra scripts/evaluate.py (data/models/calibration.json).
"""
import json
import time

import joblib
import numpy as np
import pandas as pd

from elvepred import classify, features, hourly
from elvepred.clients import gts, hydapi, openmeteo
from elvepred.model.train import FC_MODEL, MODELS, QUANTILES
from elvepred.settings import DATA, load_rivers

HISTORY_DAYS = 60
OBSERVED_DAYS = 30
OBSERVED_HOURS = 72
# Timesprognosen trekkes i log-rom mot døgnprognosens bane med vekt α(k), lineært fra 0 ved 6 t til 1
# ved 48 t. Backtest (scripts/backtest_blend.py): beste α ≈ 0.25 / 0.5 / 0.75 / 1 ved 12 / 24 / 36 / 48 t,
# og NSE ved 48 t går fra 0.65 til 0.72. Da møtes de to prognosene ved 48 t uten sprang.
BLEND_K0, BLEND_K1 = 6, hourly.MAX_K
HOURLY_HISTORY = hourly.PAST + 48  # timer med timesmålinger som timesmodellen trenger
OUT = DATA / "predictions"


def current_inputs(station: str, today: pd.Timestamp) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame]:
    start = today - pd.Timedelta(days=HISTORY_DAYS)
    q = hydapi.daily_discharge(station, start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))[["q"]]
    hq = hydapi.hourly_discharge(station, (today - pd.Timedelta(hours=HOURLY_HISTORY)).strftime("%Y-%m-%d"),
                                 today.strftime("%Y-%m-%d")).dropna()
    end = gts.last_available(station, today)
    w = gts.frame(station, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    fch = openmeteo.live_hourly(station, FC_MODEL)
    return w.join(q, how="left").asfreq("D"), hq, openmeteo.daily_forecasts(fch), fch


def predict_all(today: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict]:
    today = (today or pd.Timestamp.today()).normalize()
    models = {(h, n): joblib.load(MODELS / f"h{h}_{n}.joblib") for h in features.HORIZONS for n in QUANTILES}
    calib = {int(h): v for h, v in json.loads((MODELS / "calibration.json").read_text()).items()}
    hmodels = {n: joblib.load(MODELS / f"hourly_{n}.joblib") for n in QUANTILES}
    hcal = {int(k): v for k, v in json.loads((MODELS / "hourly_calibration.json").read_text()).items()}
    hk = sorted(hcal)
    rows, obs, hrows, timing = [], [], [], {"fetch_s": 0.0, "predict_s": 0.0}
    for r in load_rivers():
        st = r["station"]
        t0 = time.perf_counter()
        df, hq, fc, fch = current_inputs(st, today)
        timing["fetch_s"] += time.perf_counter() - t0
        t0 = time.perf_counter()
        issue = df["q"].last_valid_index()
        d = df["q"].dropna().iloc[-OBSERVED_DAYS:]
        obs.append(pd.DataFrame({"river": r["id"], "time": d.index, "q": d.values, "resolution": "day"}))
        hobs = hq[hq.index > hq.index[-1] - pd.Timedelta(hours=OBSERVED_HOURS)]
        obs.append(pd.DataFrame({"river": r["id"], "time": hobs.index, "q": hobs.values, "resolution": "hour"}))
        days = []
        # klokkeslett (UTC) for siste timesmåling, regnet fra starten av dagen etter issue
        hour = int(min(23, (hq.index[-1] - issue - pd.Timedelta(days=1)) / pd.Timedelta(hours=1)))
        for h in features.HORIZONS:
            if h >= 2 and pd.isna(fc[f"rr_fc{h}"].get(issue)):
                break
            X = features.build(df, h, "wx_fc", hq=hq, hour=hour, fc=fc)
            X["station"] = pd.Categorical([st] * len(X), categories=models[(h, "p50")]["stations"])
            x = X.loc[[issue]]
            row = {"river": r["id"], "station": st, "issue_date": issue, "date": issue + pd.Timedelta(days=h),
                   "horizon": h, "q_yesterday": float(df.loc[issue, "q"]), "q_now": float(hq.iloc[-1]),
                   "q_now_time": hq.index[-1]}
            adj = {"p10": -calib[h]["p10"], "p50": 0.0, "p90": calib[h]["p90"]}
            for n in QUANTILES:
                m = models[(h, n)]
                row[n] = float(x["lq0"].iloc[0] + m["model"].predict(x[m["cols"]])[0] + adj[n])  # log1p
            row["rr_forecast"] = float(df["rr"].get(row["date"]) if h == 1 else fc[f"rr_fc{h}"].get(issue))
            row["tm_forecast"] = float(df["tm"].get(row["date"]) if h == 1 else fc[f"tm_fc{h}"].get(issue))
            days.append(row)
        hrows.append(predict_hourly(r, hq, fch, df, hmodels, hcal, hk, days, issue))
        t = r["thresholds"]
        for row in days:
            # kvantilkryssing kan skje med separate modeller – sorter
            row["p10"], row["p50"], row["p90"] = sorted(float(np.expm1(row[n])) for n in QUANTILES)
            row["status"] = classify.LABELS[classify.interval(row["p50"], t)]
            row["prob_paddleable"] = classify.prob_between(t["minimum"], t["maximum"], row["p10"], row["p50"], row["p90"])
            row["prob_optimal"] = classify.prob_between(t["optimum"], t["maximum"], row["p10"], row["p50"], row["p90"])
        rows.extend(days)
        timing["predict_s"] += time.perf_counter() - t0
    out = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "latest.parquet")
    pd.concat(obs, ignore_index=True).to_parquet(OUT / "observed.parquet")
    pd.concat(hrows, ignore_index=True).to_parquet(OUT / "hourly.parquet")
    (OUT / "run.json").write_text(json.dumps({"run_at": pd.Timestamp.now(tz="UTC").isoformat(), **timing}))
    return out, timing


def predict_hourly(r: dict, hq: pd.Series, fch: pd.DataFrame, df: pd.DataFrame, models: dict, calib: dict,
                   ks: list[int], days: list[dict], issue: pd.Timestamp) -> pd.DataFrame:
    """p10/p50/p90 for hver time 1–48 t etter siste timesmåling, gradvis blandet med døgnprognosen.

    `days` er døgnprognosene i log1p-rom (døgn h plottes kl. 12 UTC på dato issue + h).
    """
    T = hq.index[-1]
    X = hourly.build(hq, fch, df, pd.DatetimeIndex([T]), ks=range(1, hourly.MAX_K + 1), with_target=False)
    X["station"] = pd.Categorical([r["station"]] * len(X), categories=models["p50"]["stations"])
    k = X["k"].to_numpy()
    adj = {"p10": -np.interp(k, ks, [calib[x]["p10"] for x in ks]), "p50": 0.0,
           "p90": np.interp(k, ks, [calib[x]["p90"] for x in ks])}
    out = pd.DataFrame({"river": r["id"], "issue_time": T, "time": T + pd.to_timedelta(k, unit="h"), "k": k})
    a = np.clip((k - BLEND_K0) / (BLEND_K1 - BLEND_K0), 0, 1) if days else np.zeros(len(k))
    pos = ((out["time"] - issue - pd.Timedelta(hours=12)) / pd.Timedelta(days=1)).to_numpy()
    hs = [d["horizon"] for d in days]
    for n, m in models.items():
        lh = X["lq_now"].to_numpy() + m["model"].predict(X[m["cols"]]) + adj[n]
        ld = np.interp(pos, hs, [d[n] for d in days]) if days else lh
        out[n] = np.expm1((1 - a) * lh + a * ld)
    out[["p10", "p50", "p90"]] = np.sort(out[["p10", "p50", "p90"]].to_numpy(), axis=1)
    t = r["thresholds"]
    out["status"] = [classify.LABELS[classify.interval(v, t)] for v in out["p50"]]
    out["prob_paddleable"] = [classify.prob_between(t["minimum"], t["maximum"], a, b, c)
                              for a, b, c in out[["p10", "p50", "p90"]].to_numpy()]
    out["rr"] = fch["rr_l0"].reindex(out["time"]).to_numpy()
    return out

