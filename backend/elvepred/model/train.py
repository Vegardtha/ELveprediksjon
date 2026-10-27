"""Trener endelige modeller på all historikk: LightGBM-kvantiler per horisont, felles for alle stasjoner.

Driftsoppsett (valgt ut fra scripts/evaluate_fc.py): vær framover fra MET Nordic via Open-Meteo,
trent på fasitvær før prognosearkivet (mars 2024) og ekte arkiverte prognoser etter.
"""
import json
import time

import joblib
import lightgbm as lgb
import pandas as pd

from elvepred import features
from elvepred.settings import DATA, load_rivers

PARAMS = dict(learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=8)
QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
N_ESTIMATORS = 600
MODELS = DATA / "models"
WEATHER, FC_MODEL = "wx_mixed", "metno_seamless"


def train_all() -> dict:
    stations = [r["station"] for r in load_rivers()]
    MODELS.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    for h in features.HORIZONS:
        d = features.dataset(stations, h, WEATHER, fc_model=FC_MODEL)
        cols = [c for c in d.columns if c not in features.NON_FEATURES]
        for name, a in QUANTILES.items():
            m = lgb.LGBMRegressor(objective="quantile", alpha=a, n_estimators=N_ESTIMATORS, **PARAMS)
            m.fit(d[cols], d["y"], categorical_feature=["station"])
            joblib.dump({"model": m, "cols": cols, "stations": stations}, MODELS / f"h{h}_{name}.joblib")
    info = {"trained_at": pd.Timestamp.now().isoformat(), "train_seconds": time.perf_counter() - t0,
            "weather": WEATHER, "fc_model": FC_MODEL}
    (MODELS / "info.json").write_text(json.dumps(info, indent=1))
    return info
