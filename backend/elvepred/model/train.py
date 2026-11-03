"""Trener endelige modeller på all historikk: XGBoost-kvantiler per horisont, felles for alle stasjoner.

Driftsoppsett (valgt ut fra scripts/evaluate_fc.py): vær framover fra MET Nordic via Open-Meteo,
trent på fasitvær før prognosearkivet (mars 2024) og ekte arkiverte prognoser etter.

Trening går på GPU (CUDA) når den finnes, ellers CPU; modellene lagres for CPU-prediksjon.
XGBoost på CUDA er ~3× raskere enn LightGBM på CPU med samme treffsikkerhet (h=3, p50: NSE 0.909 mot 0.908).
"""
import json
import time

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from elvepred import features, upstream
from elvepred.settings import DATA, load_stations

# tilsvarer tidligere LightGBM-oppsett (num_leaves=31, min_child_samples=40)
PARAMS = dict(learning_rate=0.03, max_depth=0, max_leaves=31, grow_policy="lossguide", min_child_weight=40,
              subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, tree_method="hist", enable_categorical=True,
              max_cat_to_onehot=1, n_jobs=8)
QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
N_ESTIMATORS = 600
MODELS = DATA / "models"
WEATHER, FC_MODEL = "wx_mixed", "metno_seamless"
# Valgt med scripts/eval_fast.py: feltsignatur og resesjonskurve per stasjon (features.signature), vekt på rader
# med ekte værprognose (W_FC) og på hendelser der elva stiger, faller eller det er meldt mye regn (W_EVENT)
SIGNATURES = True
# vannføring ved nærmeste målestasjon oppstrøms (elvepred.upstream), for stasjonene som har en
UPSTREAM = True
W_FC, W_EVENT = 2.0, 3.0


def event(d: pd.DataFrame) -> np.ndarray:
    """Rader der elva er i bevegelse eller det er meldt mye regn – bestemt av features, ikke av fasit,
    så vektingen ikke forskyver kvantilene."""
    return ((d["rr_fsum"] >= 15) | (d["dlq1"].abs() >= 0.1)
            | (d["dlq_max7"] > -0.05) & (d["lq_max7"] - d["lq_mean30"] > 0.3)).to_numpy()


def weights(d: pd.DataFrame, w_fc: float = W_FC, w_event: float = W_EVENT) -> np.ndarray:
    return (1 + (w_fc - 1) * d["wx_fc"].to_numpy()) * (1 + (w_event - 1) * event(d))


def stations_with_data() -> list[str]:
    """Stasjoner med all rådata, også prognosearkivet (nye stasjoner kommer med når hentingen er ferdig)."""
    raw = DATA / "raw"
    return [r["station"] for r in load_stations()
            if all((raw / sub / f"{r['station']}.parquet").exists()
                   for sub in ("hydapi", "gts", "hydapi_hourly", f"forecasts/{FC_MODEL}"))]


def _device() -> str:
    try:
        xgb.XGBRegressor(n_estimators=1, device="cuda").fit([[0.0], [1.0]], [0.0, 1.0])
        return "cuda"
    except Exception:
        return "cpu"


DEVICE = _device()


def fit_quantile(X: pd.DataFrame, y: pd.Series, alpha: float, n_estimators: int, eval_set=None,
                 early_stopping: int | None = None, sample_weight=None, **params) -> xgb.XGBRegressor:
    """Kvantilmodell; `station` må være pandas-kategori. Returneres klar for prediksjon på CPU."""
    m = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=alpha, n_estimators=n_estimators,
                         device=DEVICE, early_stopping_rounds=early_stopping, **(PARAMS | params))
    m.fit(X, y, eval_set=eval_set, sample_weight=sample_weight, verbose=False)
    m.set_params(device="cpu")
    return m


def train_all(stations: list[str] | None = None) -> dict:
    stations = stations or stations_with_data()
    MODELS.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    sigs = {st: features.signature(features.load_station(st)) for st in stations} if SIGNATURES else None
    # lagres i modellen, så nye stasjoner i catchments.geojson ikke bytter oppstrømsstasjon uten ny trening
    ups = {st: p for st, p in upstream.pairs().items() if st in stations} if UPSTREAM else {}
    for h in features.HORIZONS:
        d = features.dataset(stations, h, WEATHER, fc_model=FC_MODEL, sig_until=SIGNATURES or None,
                             upstream=UPSTREAM)
        cols = [c for c in d.columns if c not in features.NON_FEATURES]
        w = weights(d)
        for name, a in QUANTILES.items():
            m = fit_quantile(d[cols], d["y"], a, N_ESTIMATORS, sample_weight=w)
            joblib.dump({"model": m, "cols": cols, "stations": stations, "signatures": sigs, "upstream": ups},
                        MODELS / f"h{h}_{name}.joblib")
    info = {"trained_at": pd.Timestamp.now().isoformat(), "train_seconds": time.perf_counter() - t0,
            "weather": WEATHER, "fc_model": FC_MODEL, "library": f"xgboost {xgb.__version__}", "device": DEVICE,
            "stations": len(stations), "signatures": SIGNATURES, "w_fc": W_FC, "w_event": W_EVENT,
            "upstream": len(ups)}
    (MODELS / "info.json").write_text(json.dumps(info, indent=1))
    return info
