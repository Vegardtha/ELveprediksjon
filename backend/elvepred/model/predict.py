"""Prediksjon: siste døgn- og timesvannføring (HydAPI), observert vær/snø/HBV-tilstand (GTS) og
værprognose (MET Nordic via Open-Meteo) → p10/p50/p90 per dag.

p10/p90 justeres med konforme tillegg fra scripts/evaluate.py (data/models/calibration.json).
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

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
# seNorge (GTS) oppdateres én gang i døgnet, om morgenen. Feltmiddelet (~115 kall per stasjon) hentes derfor
# bare ved første kjøring hver dag og første kjøring etter GTS_REFRESH_UTC, og ellers fra hurtiglageret.
GTS_CACHE = DATA / "cache" / "gts"
GTS_REFRESH_UTC = 8
GTS_STALE_DAYS = 2  # eldre hurtiglager brukes bare hvis GTS ikke svarer
FETCH_WORKERS = 4


def gts_state(station: str, today: pd.Timestamp) -> tuple[pd.DataFrame, bool]:
    """Feltmiddel fra GTS for HISTORY_DAYS bakover til siste prognosedag. Returnerer (frame, fra hurtiglager)."""
    f, meta = GTS_CACHE / f"{station}.parquet", GTS_CACHE / f"{station}.json"
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    cached = pd.Timestamp(json.loads(meta.read_text())["fetched_at"]) if f.exists() and meta.exists() else None
    fresh = cached is not None and cached.normalize() == now.normalize() and (
        cached.hour >= GTS_REFRESH_UTC or now.hour < GTS_REFRESH_UTC)
    if fresh:
        return pd.read_parquet(f), True
    start = today - pd.Timedelta(days=HISTORY_DAYS)
    try:
        end = gts.last_available(station, today)
        w = gts.frame(station, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    except Exception as e:
        if cached is None or now - cached > pd.Timedelta(days=GTS_STALE_DAYS):
            raise
        print(f"::warning::{station}: GTS feilet ({type(e).__name__}), bruker hurtiglager fra {cached}", file=sys.stderr)
        return pd.read_parquet(f), True
    GTS_CACHE.mkdir(parents=True, exist_ok=True)
    w.to_parquet(f)
    meta.write_text(json.dumps({"fetched_at": now.isoformat()}))
    return w, False


def current_inputs(station: str, today: pd.Timestamp) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, bool]:
    start = today - pd.Timedelta(days=HISTORY_DAYS)
    q = hydapi.daily_discharge(station, start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))[["q"]]
    hq = hydapi.hourly_discharge(station, (today - pd.Timedelta(hours=HOURLY_HISTORY)).strftime("%Y-%m-%d"),
                                 today.strftime("%Y-%m-%d")).dropna()
    w, from_cache = gts_state(station, today)
    w = w[w.index >= start]
    fch = openmeteo.live_hourly(station, FC_MODEL)
    return w.join(q, how="left").asfreq("D"), hq, openmeteo.daily_forecasts(fch), fch, from_cache


def measured(station: str, today: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    """Bare målt døgn- og timesvannføring, for seksjoner uten prognose."""
    q = hydapi.daily_discharge(station, (today - pd.Timedelta(days=OBSERVED_DAYS)).strftime("%Y-%m-%d"),
                               today.strftime("%Y-%m-%d"))["q"].dropna()
    hq = hydapi.hourly_discharge(station, (today - pd.Timedelta(hours=OBSERVED_HOURS)).strftime("%Y-%m-%d"),
                                 today.strftime("%Y-%m-%d")).dropna()
    return q, hq


def fetch_all(stations: list[str], today: pd.Timestamp) -> dict[str, tuple | Exception]:
    """Henter inndata for alle stasjoner parallelt. En feilet stasjon gir unntaket i stedet for data."""
    def one(st):
        try:
            return current_inputs(st, today)
        except Exception as e:  # én utilgjengelig kilde skal ikke stoppe de andre elvene
            return e
    with ThreadPoolExecutor(FETCH_WORKERS) as ex:
        return dict(zip(stations, ex.map(one, stations)))


def predict_all(today: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict]:
    today = (today or pd.Timestamp.today()).normalize()
    models = {(h, n): joblib.load(MODELS / f"h{h}_{n}.joblib") for h in features.HORIZONS for n in QUANTILES}
    calib = {int(h): v for h, v in json.loads((MODELS / "calibration.json").read_text()).items()}
    hmodels = {n: joblib.load(MODELS / f"hourly_{n}.joblib") for n in QUANTILES}
    hcal = {int(k): v for k, v in json.loads((MODELS / "hourly_calibration.json").read_text()).items()}
    hk = sorted(hcal)
    rivers = load_rivers()
    # seksjoner med `forecast: false` får bare målt vannføring
    observe = [r for r in rivers if r.get("forecast") is False]
    rivers = [r for r in rivers if r.get("forecast") is not False]
    t0 = time.perf_counter()
    inputs = fetch_all(list(dict.fromkeys(r["station"] for r in rivers)), today)
    timing = {"fetch_s": time.perf_counter() - t0, "predict_s": 0.0,
              "gts_cached": sum(1 for v in inputs.values() if not isinstance(v, Exception) and v[4])}
    rows, obs, hrows, failed = [], [], [], []
    by_station = {}
    for r in rivers:
        by_station.setdefault(r["station"], []).append(r)
    for st, secs in by_station.items():
        if isinstance(inputs[st], Exception):
            e = inputs[st]
            print(f"::warning::{st}: kunne ikke hente data ({type(e).__name__}: {e})", file=sys.stderr)
            failed.extend(r["id"] for r in secs)
            continue
        df, hq, fc, fch, _ = inputs[st]
        t0 = time.perf_counter()
        issue = df["q"].last_valid_index()
        d = df["q"].dropna().iloc[-OBSERVED_DAYS:]
        hobs = hq[hq.index > hq.index[-1] - pd.Timedelta(hours=OBSERVED_HOURS)]
        days = []
        # klokkeslett (UTC) for siste timesmåling, regnet fra starten av dagen etter issue
        hour = int(min(23, (hq.index[-1] - issue - pd.Timedelta(days=1)) / pd.Timedelta(hours=1)))
        for h in features.HORIZONS:
            if h >= 2 and pd.isna(fc[f"rr_fc{h}"].get(issue)):
                break
            X = features.build(df, h, "wx_fc", hq=hq, hour=hour, fc=fc)
            X["station"] = pd.Categorical([st] * len(X), categories=models[(h, "p50")]["stations"])
            x = X.loc[[issue]]
            row = {"station": st, "issue_date": issue, "date": issue + pd.Timedelta(days=h),
                   "horizon": h, "q_yesterday": float(df.loc[issue, "q"]), "q_now": float(hq.iloc[-1]),
                   "q_now_time": hq.index[-1]}
            adj = {"p10": -calib[h]["p10"], "p50": 0.0, "p90": calib[h]["p90"]}
            for n in QUANTILES:
                m = models[(h, n)]
                row[n] = float(x["lq0"].iloc[0] + m["model"].predict(x[m["cols"]])[0] + adj[n])  # log1p
            row["rr_forecast"] = float(df["rr"].get(row["date"]) if h == 1 else fc[f"rr_fc{h}"].get(issue))
            row["tm_forecast"] = float(df["tm"].get(row["date"]) if h == 1 else fc[f"tm_fc{h}"].get(issue))
            days.append(row)
        hourly_q = predict_hourly(st, hq, fch, df, hmodels, hcal, hk, days, issue)
        for row in days:
            # kvantilkryssing kan skje med separate modeller – sorter
            row["p10"], row["p50"], row["p90"] = sorted(float(np.expm1(row[n])) for n in QUANTILES)
        # prognosen er per målestasjon; status og sannsynligheter per seksjon
        for r in secs:
            t = r["thresholds"]
            obs.append(pd.DataFrame({"river": r["id"], "time": d.index, "q": d.values, "resolution": "day"}))
            obs.append(pd.DataFrame({"river": r["id"], "time": hobs.index, "q": hobs.values, "resolution": "hour"}))
            for row in days:
                rows.append(row | {"river": r["id"], **classified(row["p10"], row["p50"], row["p90"], t, optimal=True)})
            hrows.append(hourly_q.assign(river=r["id"], **pd.DataFrame(
                [classified(*v, t) for v in hourly_q[["p10", "p50", "p90"]].to_numpy()], index=hourly_q.index)))
        timing["predict_s"] += time.perf_counter() - t0
    for r in observe:
        try:
            d, hobs = measured(r["station"], today)
        except Exception as e:
            print(f"::warning::{r['station']}: kunne ikke hente målinger ({type(e).__name__}: {e})", file=sys.stderr)
            failed.append(r["id"])
            continue
        obs.append(pd.DataFrame({"river": r["id"], "time": d.index, "q": d.values, "resolution": "day"}))
        obs.append(pd.DataFrame({"river": r["id"], "time": hobs.index, "q": hobs.values, "resolution": "hour"}))
    if not rows:
        raise RuntimeError(f"ingen elver fikk prognose (feilet: {failed})")
    out = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "latest.parquet")
    pd.concat(obs, ignore_index=True).to_parquet(OUT / "observed.parquet")
    pd.concat(hrows, ignore_index=True).to_parquet(OUT / "hourly.parquet")
    (OUT / "run.json").write_text(json.dumps({"run_at": pd.Timestamp.now(tz="UTC").isoformat(), "failed": failed, **timing}))
    return out, timing


def classified(p10: float, p50: float, p90: float, t: dict, optimal: bool = False) -> dict:
    out = {"status": classify.LABELS[classify.interval(p50, t)],
           "prob_paddleable": classify.prob_between(t["minimum"], t["maximum"], p10, p50, p90)}
    if optimal:
        out["prob_optimal"] = classify.prob_between(t["optimum"], t["maximum"], p10, p50, p90)
    return out


def predict_hourly(station: str, hq: pd.Series, fch: pd.DataFrame, df: pd.DataFrame, models: dict, calib: dict,
                   ks: list[int], days: list[dict], issue: pd.Timestamp) -> pd.DataFrame:
    """p10/p50/p90 for hver time 1–48 t etter siste timesmåling, gradvis blandet med døgnprognosen.

    `days` er døgnprognosene i log1p-rom (døgn h plottes kl. 12 UTC på dato issue + h).
    """
    T = hq.index[-1]
    X = hourly.build(hq, fch, df, pd.DatetimeIndex([T]), ks=range(1, hourly.MAX_K + 1), with_target=False)
    X["station"] = pd.Categorical([station] * len(X), categories=models["p50"]["stations"])
    k = X["k"].to_numpy()
    adj = {"p10": -np.interp(k, ks, [calib[x]["p10"] for x in ks]), "p50": 0.0,
           "p90": np.interp(k, ks, [calib[x]["p90"] for x in ks])}
    out = pd.DataFrame({"issue_time": T, "time": T + pd.to_timedelta(k, unit="h"), "k": k})
    a = np.clip((k - BLEND_K0) / (BLEND_K1 - BLEND_K0), 0, 1) if days else np.zeros(len(k))
    pos = ((out["time"] - issue - pd.Timedelta(hours=12)) / pd.Timedelta(days=1)).to_numpy()
    hs = [d["horizon"] for d in days]
    for n, m in models.items():
        lh = X["lq_now"].to_numpy() + m["model"].predict(X[m["cols"]]) + adj[n]
        ld = np.interp(pos, hs, [d[n] for d in days]) if days else lh
        out[n] = np.expm1((1 - a) * lh + a * ld)
    out[["p10", "p50", "p90"]] = np.sort(out[["p10", "p50", "p90"]].to_numpy(), axis=1)
    out["rr"] = fch["rr_l0"].reindex(out["time"]).to_numpy()
    return out
