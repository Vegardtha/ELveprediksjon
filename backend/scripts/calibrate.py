"""Kalibrering og test av driftsoppsettet: samme features, vekter og antall trær som model/train.py.

Trening på mål før 2024-11, konform kalibrering av p10/p90 på 2024-11..2025-06, test fra 2025-07 med ekte
arkiverte værprognoser. Erstatter kalibreringsdelen av scripts/evaluate_fc.py, som bruker early stopping og
derfor ikke er samme modell som i drift.

Skriver data/models/calibration.json og data/eval/metrics_prod.json.
Med --baseline: oppsettet før feltsignaturer og vekting (2026-11-02), bare til data/eval/metrics_baseline.json.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import numpy as np
import pandas as pd

from elvepred import features
from elvepred.evaluation import scores
from elvepred.model.train import (FC_MODEL, MODELS, N_ESTIMATORS, QUANTILES, SIGNATURES, UPSTREAM, WEATHER,
                                  fit_quantile, weights)
from elvepred.settings import DATA

VAL_START, TEST_START = "2024-11-01", "2025-07-01"
BASELINE = "--baseline" in sys.argv
NEW_COLS = {"wx_fc", "dlq_max7", "days_since_max"}
stations = joblib.load(MODELS / "h1_p50.joblib")["stations"]
mean = lambda r, k: float(np.mean([v[k] for v in r.values()]))

calibration, metrics = {}, {}
for h in features.HORIZONS:
    t0 = time.perf_counter()
    sig = VAL_START if SIGNATURES and not BASELINE else None
    up = UPSTREAM and not BASELINE
    mixed = features.dataset(stations, h, WEATHER, fc_model=FC_MODEL, sig_until=sig, upstream=up)
    real = features.dataset(stations, h, "wx_fc", fc_model=FC_MODEL, sig_until=sig, upstream=up)
    target = mixed["date"] + pd.Timedelta(days=h)
    has_fc = real["rr_fsum"].notna()
    tr = (target < VAL_START).to_numpy()
    va = ((real["date"] >= VAL_START) & (target < TEST_START) & has_fc).to_numpy()
    te = ((real["date"] >= TEST_START) & has_fc).to_numpy()
    cols = [c for c in mixed.columns if c not in features.NON_FEATURES and not (BASELINE and c in NEW_COLS)]
    w = None if BASELINE else weights(mixed[tr])
    models = {n: fit_quantile(mixed.loc[tr, cols], mixed.loc[tr, "y"], a, N_ESTIMATORS, sample_weight=w)
              for n, a in QUANTILES.items()}

    yv = real.loc[va, "y"].to_numpy()
    pv = {n: m.predict(real.loc[va, cols]) for n, m in models.items()}
    lo, hi = float(np.quantile(pv["p10"] - yv, 0.9)), float(np.quantile(yv - pv["p90"], 0.9))
    calibration[h] = {"p10": lo, "p90": hi}

    t = real[te]
    y = t["y"].to_numpy()
    pt = {n: m.predict(t[cols]) for n, m in models.items()}
    model = scores(t, pd.Series(np.expm1(t["lq0"].to_numpy() + pt["p50"]), t.index))
    pers = scores(t, pd.Series(np.expm1(t["lq_now"].fillna(t["lq0"])).to_numpy(), t.index))
    cov = float(np.mean((y >= pt["p10"] - lo) & (y <= pt["p90"] + hi)))
    metrics[h] = {"model": model, "persistence_now": pers, "coverage_calibrated": cov,
                  "coverage_raw": float(np.mean((y >= pt["p10"]) & (y <= pt["p90"])))}
    print(f"h={h} NSE {mean(model, 'NSE'):.3f} (persistens {mean(pers, 'NSE'):.3f})  F1 padlbart "
          f"{mean(model, 'F1_paddleable'):.3f}  dekning {cov:.2f}  kalibrering {lo:+.3f}/{hi:+.3f} "
          f"({time.perf_counter() - t0:.0f}s)", flush=True)

if not BASELINE:
    (MODELS / "calibration.json").write_text(json.dumps(calibration, indent=1))
(DATA / "eval").mkdir(parents=True, exist_ok=True)
(DATA / "eval" / f"metrics_{'baseline' if BASELINE else 'prod'}.json").write_text(json.dumps(
    {"results": metrics, "calibration": calibration, "split": {"val_start": VAL_START, "test_start": TEST_START},
     "stations": list(stations)}, indent=1))
