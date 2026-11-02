"""Evaluerer og trener timesmodellen (1–48 t).

Splitt: trening til og med 2025-03-31, validering (kalibrering) til 2025-06-30, test etter.
Til slutt trenes endelige modeller på alle data.
Skriver data/eval/metrics_hourly.json og data/models/hourly_{p10,p50,p90}.joblib + hourly_calibration.json.
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
REPORT_K = [1, 3, 6, 12, 18, 24, 36, 48]
# Early stopping stoppet p50 etter ~125 trær og ga klart dårligere test (NSE 24 t 0.69 mot 0.78 med 600)
N_TREES = 800
# Avstand til topp, feltsignatur og resesjonskurve (som hjelper døgnmodellen) ga ingen gevinst her (2026-11-02:
# NSE likt til 24 t, -0.006/-0.010 ved 36/48 t), trolig fordi timesmodellen bare har ett år å lære av. De er derfor
# bare med i sammenligningen («uten nye» skrives da ut som «med nye»).
NEW_FEATURES = False

t0 = time.perf_counter()
# samme stasjoner som døgnmodellene (som bare tar med stasjoner med prognosearkiv)
stations = joblib.load(MODELS / "h1_p50.joblib")["stations"]
# feltsignatur fra data til og med treningsperioden i evalueringen, fra all historikk i de endelige modellene
sig_eval = {st: features.signature(features.load_station(st), TRAIN_END[:10]) for st in stations}
sig_all = {st: features.signature(features.load_station(st)) for st in stations}
d = hourly.dataset(stations, sig_eval)
all_cols = [c for c in d.columns if c not in hourly.NON_FEATURES]
NEW = {"dlq_max72", "h_since_max72", "rec_k"} | set(next(iter(sig_eval.values())))
tr, va, te = d[d.time <= TRAIN_END], d[(d.time > TRAIN_END) & (d.time <= VAL_END)], d[d.time > VAL_END]
print(f"rader: trening {len(tr)}, validering {len(va)}, test {len(te)} ({time.perf_counter() - t0:.0f}s)", flush=True)

# Sammenligning med og uten de nye featurene (avstand til topp, feltsignatur, resesjonskurve), bare p50
old_cols = [c for c in all_cols if c not in NEW]
cols, other = (all_cols, old_cols) if NEW_FEATURES else (old_cols, all_cols)
m_old = fit_quantile(tr[other], tr["y"], 0.5, N_TREES)
p_old = np.expm1(te["lq_now"].to_numpy() + m_old.predict(te[other]))
OTHER = "uten nye" if NEW_FEATURES else "med nye"

t1 = time.perf_counter()
models = {n: fit_quantile(tr[cols], tr["y"], a, N_TREES) for n, a in QUANTILES.items()}
fit_s = time.perf_counter() - t1
print(f"trent på {fit_s:.0f}s", flush=True)


def predict(x):
    return {n: m.predict(x[cols]) for n, m in models.items()}


# Konform kalibrering per k: forskyv p10/p90 i log-rom så 80 % dekning holder på validering
pv = predict(va)
calib = {}
for k in hourly.K_TRAIN:
    s = (va["k"] == k).to_numpy()
    y = va["y"].to_numpy()[s]
    calib[k] = {"p10": float(np.quantile(pv["p10"][s] - y, 0.9)), "p90": float(np.quantile(y - pv["p90"][s], 0.9))}

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
    o = scores(g, pd.Series(p_old[s], index=g.index))
    p = scores(g, pd.Series(g["q0"].to_numpy(), index=g.index))
    cov = float(np.mean((g["q_true"] >= q["p10"][s]) & (g["q_true"] <= q["p90"][s])))
    results[k] = {"model": m, "other": o, "persistence": p, "coverage": cov}
    mean = lambda r, key: np.mean([v[key] for v in r.values()])
    print(f"k={k:2d}t  NSE {mean(m, 'NSE'):.3f} ({OTHER} {mean(o, 'NSE'):.3f}, persistens {mean(p, 'NSE'):.3f})  "
          f"F1 padlbart {mean(m, 'F1_paddleable'):.2f} ({mean(p, 'F1_paddleable'):.2f})  dekning {cov:.2f}", flush=True)

(DATA / "eval").mkdir(parents=True, exist_ok=True)
(DATA / "eval" / "metrics_hourly.json").write_text(json.dumps(
    {"results": results, "calibration": calib, "fit_s": fit_s, "split": {"train_end": TRAIN_END, "val_end": VAL_END}},
    indent=1, default=float))

# Endelige modeller på alt
t1 = time.perf_counter()
d = hourly.dataset(stations, sig_all if NEW_FEATURES else None)
for n, a in QUANTILES.items():
    m = fit_quantile(d[cols], d["y"], a, N_TREES)
    joblib.dump({"model": m, "cols": cols, "stations": stations, "signatures": sig_all if NEW_FEATURES else None},
                MODELS / f"hourly_{n}.joblib")
(MODELS / "hourly_calibration.json").write_text(json.dumps(calib, indent=1))
print(f"endelige modeller trent på {time.perf_counter() - t1:.0f}s, totalt {time.perf_counter() - t0:.0f}s")
