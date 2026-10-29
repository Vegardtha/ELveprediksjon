"""Trener endelige modeller på all historikk: XGBoost-kvantiler per horisont, felles for alle stasjoner.

Driftsoppsett (valgt ut fra scripts/evaluate_fc.py): vær framover fra MET Nordic via Open-Meteo,
trent på fasitvær før prognosearkivet (mars 2024) og ekte arkiverte prognoser etter.

Trening går på GPU (CUDA) når den finnes, ellers CPU; modellene lagres for CPU-prediksjon.
XGBoost på CUDA er ~3× raskere enn LightGBM på CPU med samme treffsikkerhet (h=3, p50: NSE 0.909 mot 0.908).
"""
import json
import time

import joblib
import pandas as pd
import xgboost as xgb

from elvepred import features
from elvepred.settings import DATA, load_stations

# tilsvarer tidligere LightGBM-oppsett (num_leaves=31, min_child_samples=40)
PARAMS = dict(learning_rate=0.03, max_depth=0, max_leaves=31, grow_policy="lossguide", min_child_weight=40,
              subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, tree_method="hist", enable_categorical=True,
              max_cat_to_onehot=1, n_jobs=8)
QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
N_ESTIMATORS = 600
MODELS = DATA / "models"
WEATHER, FC_MODEL = "wx_mixed", "metno_seamless"


def _device() -> str:
    try:
        xgb.XGBRegressor(n_estimators=1, device="cuda").fit([[0.0], [1.0]], [0.0, 1.0])
        return "cuda"
    except Exception:
        return "cpu"


DEVICE = _device()


def fit_quantile(X: pd.DataFrame, y: pd.Series, alpha: float, n_estimators: int, eval_set=None,
                 early_stopping: int | None = None) -> xgb.XGBRegressor:
    """Kvantilmodell; `station` må være pandas-kategori. Returneres klar for prediksjon på CPU."""
    m = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=alpha, n_estimators=n_estimators,
                         device=DEVICE, early_stopping_rounds=early_stopping, **PARAMS)
    m.fit(X, y, eval_set=eval_set, verbose=False)
    m.set_params(device="cpu")
    return m


def train_all() -> dict:
    stations = [r["station"] for r in load_stations()]
    MODELS.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    for h in features.HORIZONS:
        d = features.dataset(stations, h, WEATHER, fc_model=FC_MODEL)
        cols = [c for c in d.columns if c not in features.NON_FEATURES]
        for name, a in QUANTILES.items():
            m = fit_quantile(d[cols], d["y"], a, N_ESTIMATORS)
            joblib.dump({"model": m, "cols": cols, "stations": stations}, MODELS / f"h{h}_{name}.joblib")
    info = {"trained_at": pd.Timestamp.now().isoformat(), "train_seconds": time.perf_counter() - t0,
            "weather": WEATHER, "fc_model": FC_MODEL, "library": f"xgboost {xgb.__version__}", "device": DEVICE}
    (MODELS / "info.json").write_text(json.dumps(info, indent=1))
    return info
