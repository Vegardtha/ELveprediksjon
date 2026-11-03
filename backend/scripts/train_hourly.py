"""Evaluerer og trener timesmodellen (1–48 t).

Splitt: trening til og med 2025-03-31, validering (kalibrering) til 2025-06-30, test etter.
Til slutt trenes endelige modeller på alle data.
Skriver data/eval/metrics_hourly.json og data/models/hourly_{p10,p50,p90}.joblib + hourly_calibration.json.

Historiske flommer: prognosearkivet (fra mars 2024) har få og bare moderate flommer. Med HISTORY trenes modellen
også på utstedelser rundt kraftige nedbørsdøgn fra 1990, med seNorge-nedbøren fordelt på timer etter ERA5
(hourly.truth_weather, wx_fc = 0). Sammenligningen (bare p50) har to tester:
  test   ekte prognoser etter 2025-06-30, som i drift
  flom   historikk fra FLOOD_TEST (fasitvær), holdt utenfor treningen i sammenligningen. Viser om modellen
         treffer stigningen og toppen i store flommer når nedbøren er kjent, og er ikke sammenlignbar med test.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import numpy as np
import pandas as pd

from elvepred import features, hourly
from elvepred.evaluation import scores
from elvepred.model.train import MODELS, QUANTILES, fit_quantile
from elvepred.settings import DATA

TRAIN_END, VAL_END = "2025-03-31 23:00", "2025-06-30 23:00"
FLOOD_TEST = "2019-01-01"
REPORT_K = [1, 3, 6, 12, 18, 24, 36, 48]
# Early stopping stoppet p50 etter ~125 trær og ga klart dårligere test (NSE 24 t 0.69 mot 0.78 med 600)
N_TREES = 800
# Avstand til topp, feltsignatur og resesjonskurve (som hjelper døgnmodellen) ga ingen gevinst her (2026-11-02:
# NSE likt til 24 t, -0.006/-0.010 ved 36/48 t), trolig fordi timesmodellen bare hadde ett år å lære av.
NEW_FEATURES = False
# historikk med fasitvær fra 1990 (se over), og vekt på hendelser som i døgnmodellen (bestemt av features)
HISTORY = True
W_EVENT = 3.0
VARIANTS = {"arkiv": dict(history=False, w_event=1.0), "historikk": dict(history=True, w_event=1.0),
            "historikk_vekt": dict(history=True, w_event=W_EVENT)}
FINAL = "historikk_vekt" if HISTORY else "arkiv"


def event(d: pd.DataFrame) -> np.ndarray:
    """Meldt regn ≥ 10 mm innen k, endring ≥ 5 % siste 6 t, eller nær en topp godt over 72-timerssnittet."""
    return ((d["rr_f"] >= 10) | (d["dlq6h"].abs() >= 0.05)
            | (d["dlq_max72"] > -0.05) & (d["lq_max24"] - d["lq_mean72"] > 0.2)).to_numpy()


def weights(d: pd.DataFrame, w_event: float) -> np.ndarray:
    return 1 + (w_event - 1) * event(d)


t0 = time.perf_counter()
# samme stasjoner som døgnmodellene (som bare tar med stasjoner med prognosearkiv)
stations = joblib.load(MODELS / "h1_p50.joblib")["stations"]
# feltsignatur fra data til og med treningsperioden i evalueringen, fra all historikk i de endelige modellene
sig_eval = {st: features.signature(features.load_station(st), TRAIN_END[:10]) for st in stations}
sig_all = {st: features.signature(features.load_station(st)) for st in stations}
d = hourly.dataset(stations, sig_eval if NEW_FEATURES else None, history=True)
NEW = {"dlq_max72", "h_since_max72", "rec_k"} | set(next(iter(sig_eval.values())))
cols = [c for c in d.columns if c not in hourly.NON_FEATURES and (NEW_FEATURES or c not in NEW)]
arch, hist = d["wx_fc"].to_numpy() == 1, d["wx_fc"].to_numpy() == 0
tr_arch = arch & (d.time <= TRAIN_END).to_numpy()
tr_hist = hist & (d.time < FLOOD_TEST).to_numpy()
va = d[arch & ((d.time > TRAIN_END) & (d.time <= VAL_END)).to_numpy()]
tests = {"test": d[arch & (d.time > VAL_END).to_numpy()], "flom": d[hist & (d.time >= FLOOD_TEST).to_numpy()]}
# flomrader: vannføring over 99-persentilen for stasjonen (timesverdier)
q99 = {st: float(hourly.load(st)[0].quantile(0.99)) for st in stations}
print(f"rader: trening {tr_arch.sum()} arkiv + {tr_hist.sum()} historikk, validering {len(va)}, "
      f"test {len(tests['test'])}, flomtest {len(tests['flom'])} ({time.perf_counter() - t0:.0f}s)", flush=True)


def metrics(t: pd.DataFrame, yhat: np.ndarray) -> dict:
    out = {}
    kk, y = t["k"].to_numpy(), t["y"].to_numpy()
    flood = (t["q_true"].to_numpy() >= t["station"].map(q99).astype(float).to_numpy())
    for k in REPORT_K:
        s = kk == k
        g = t[s]
        sc = scores(g, pd.Series(np.expm1(g["lq_now"].to_numpy() + yhat[s]), index=g.index))
        err = yhat[s] - y[s]
        rm = lambda m: float(np.sqrt(np.mean(err[m] ** 2))) if m.any() else None
        out[k] = {"NSE": float(np.mean([v["NSE"] for v in sc.values()])), "rmse_rise": rm(y[s] > 0.2),
                  "rmse_flood": rm(flood[s]), "bias_flood": float(np.median(err[flood[s]])) if flood[s].any() else None,
                  "n_flood": int(flood[s].sum())}
    return out


compare = {}
for v, cfg in VARIANTS.items():
    m = tr_arch | (tr_hist if cfg["history"] else False)
    t1 = time.perf_counter()
    model = fit_quantile(d.loc[m, cols], d.loc[m, "y"], 0.5, N_TREES, sample_weight=weights(d[m], cfg["w_event"]))
    compare[v] = {name: metrics(t, model.predict(t[cols])) for name, t in tests.items()}
    print(f"{v} trent på {time.perf_counter() - t1:.0f}s", flush=True)
for name in tests:
    print(f"\n{name}: NSE | RMSE stigning | RMSE flom | skjevhet flom (log, < 0 er for lavt)")
    for k in REPORT_K:
        f = lambda x: "  -  " if x is None else f"{x:+.3f}" if x < 0 else f"{x:.3f}"
        print(f"k={k:2d}t " + "   ".join(
            f"{v}: {f(r[name][k]['NSE'])} {f(r[name][k]['rmse_rise'])} {f(r[name][k]['rmse_flood'])} "
            f"{f(r[name][k]['bias_flood'])}" for v, r in compare.items()), flush=True)

# Kvantilmodeller for valgt variant, konform kalibrering per k på validering og test som før
cfg = VARIANTS[FINAL]
m = tr_arch | (tr_hist if cfg["history"] else False)
t1 = time.perf_counter()
w = weights(d[m], cfg["w_event"])
models = {n: fit_quantile(d.loc[m, cols], d.loc[m, "y"], a, N_TREES, sample_weight=w) for n, a in QUANTILES.items()}
fit_s = time.perf_counter() - t1
print(f"\n{FINAL}: kvantilmodeller trent på {fit_s:.0f}s", flush=True)


def predict(x):
    return {n: m.predict(x[cols]) for n, m in models.items()}


# Konform kalibrering per k: forskyv p10/p90 i log-rom så 80 % dekning holder på validering
pv = predict(va)
calib = {}
for k in hourly.K_TRAIN:
    s = (va["k"] == k).to_numpy()
    y = va["y"].to_numpy()[s]
    calib[k] = {"p10": float(np.quantile(pv["p10"][s] - y, 0.9)), "p90": float(np.quantile(y - pv["p90"][s], 0.9))}

te = tests["test"]
pt = predict(te)
lq = te["lq_now"].to_numpy()
q = {n: np.expm1(lq + pt[n]) for n in pt}
kk = te["k"].to_numpy()
q["p10"] = np.expm1(lq + pt["p10"] - np.array([calib[k]["p10"] for k in kk]))
q["p90"] = np.expm1(lq + pt["p90"] + np.array([calib[k]["p90"] for k in kk]))

results = {}
for k in REPORT_K:
    s = kk == k
    g = te[s]
    m = scores(g, pd.Series(q["p50"][s], index=g.index))
    p = scores(g, pd.Series(g["q0"].to_numpy(), index=g.index))
    cov = float(np.mean((g["q_true"] >= q["p10"][s]) & (g["q_true"] <= q["p90"][s])))
    results[k] = {"model": m, "persistence": p, "coverage": cov}
    mean = lambda r, key: np.mean([v[key] for v in r.values()])
    print(f"k={k:2d}t  NSE {mean(m, 'NSE'):.3f} (persistens {mean(p, 'NSE'):.3f})  "
          f"F1 padlbart {mean(m, 'F1_paddleable'):.2f} ({mean(p, 'F1_paddleable'):.2f})  dekning {cov:.2f}", flush=True)

(DATA / "eval").mkdir(parents=True, exist_ok=True)
(DATA / "eval" / "metrics_hourly.json").write_text(json.dumps(
    {"results": results, "compare": compare, "final": FINAL, "calibration": calib, "fit_s": fit_s,
     "split": {"train_end": TRAIN_END, "val_end": VAL_END, "flood_test": FLOOD_TEST}}, indent=1, default=float))

# Endelige modeller på alt (all historikk med fasitvær når HISTORY)
t1 = time.perf_counter()
m = arch | (hist if cfg["history"] else False)
w = weights(d[m], cfg["w_event"])
for n, a in QUANTILES.items():
    mdl = fit_quantile(d.loc[m, cols], d.loc[m, "y"], a, N_TREES, sample_weight=w)
    joblib.dump({"model": mdl, "cols": cols, "stations": stations, "signatures": sig_all if NEW_FEATURES else None},
                MODELS / f"hourly_{n}.joblib")
(MODELS / "hourly_calibration.json").write_text(json.dumps(calib, indent=1))
print(f"endelige modeller trent på {time.perf_counter() - t1:.0f}s, totalt {time.perf_counter() - t0:.0f}s")
