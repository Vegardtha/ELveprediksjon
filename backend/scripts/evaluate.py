"""Tidsbasert evaluering og kalibrering av usikkerhetsbåndet.

Trening ..2021, validering (early stopping + kalibrering) 2022, test 2023..i dag.
Variant «perfekt vær»: arkiverte værverdier for t+1..t+h (øvre grense for skill).
Variant «simulert prognose»: samme modell, men framtidig vær påføres feil som vokser med
ledetid (antatt, grovt kalibrert mot typisk nedbørsprognoseskill) – realistisk anslag.

Kalibrering (konform kvantilregresjon, CQR): på valideringsåret med simulert prognosefeil
finnes tillegg i log-rom til p10 og p90 slik at hver hale bommer i 10 % av tilfellene.
Tilleggene skrives til data/models/calibration.json og brukes av predict.py.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from elvepred import features
from elvepred.evaluation import fit_models, perturb_gts as perturb, scores, stations
from elvepred.model.train import MODELS
from elvepred.settings import DATA

TRAIN_END, VAL_END = "2021-12-31", "2022-12-31"


def predict_log(models, d, cols):
    return {n: m.predict(d[cols]) for n, m in models.items()}


to_q = lambda y, d: pd.Series(np.expm1(d["lq0"].values + y), d.index)
results, coverage, calibration = {}, {}, {}
timing = {"train_s": 0.0, "predict_s": 0.0, "rows_train": 0}
for nowcast in (False, True):
    model_name = "nowcast" if nowcast else "daily"
    for h in features.HORIZONS:
        d = features.dataset(list(stations), h, "gts", nowcast=nowcast)
        tr, va, te = d[d.date <= TRAIN_END], d[(d.date > TRAIN_END) & (d.date <= VAL_END)], d[d.date > VAL_END]
        cols = [c for c in d.columns if c not in features.NON_FEATURES]

        t0 = time.perf_counter()
        models = fit_models(tr, va, cols)
        if nowcast:
            timing["train_s"] += time.perf_counter() - t0
        if nowcast:
            timing["rows_train"] = max(timing["rows_train"], len(tr))

        # Kalibrering på valideringsåret med simulert prognosefeil
        pv = predict_log(models, perturb(va, h, np.random.default_rng(100 + h)), cols)
        yv = va["y"].values
        lo = float(np.quantile(pv["p10"] - yv, 0.9))
        hi = float(np.quantile(yv - pv["p90"], 0.9))
        if nowcast:
            calibration[h] = {"p10": lo, "p90": hi}

        for variant, tt in (("perfect_weather", te), ("simulated_forecast", perturb(te, h, np.random.default_rng(h)))):
            t0 = time.perf_counter()
            p = predict_log(models, tt, cols)
            if nowcast:
                timing["predict_s"] += time.perf_counter() - t0
            res = {model_name: scores(tt, to_q(p["p50"], tt))}
            if variant == "perfect_weather":
                res["persistence_daily"] = scores(tt, tt["q0"])
                if nowcast:
                    res["persistence_now"] = scores(tt, pd.Series(np.expm1(tt["lq_now"].fillna(tt["lq0"])).values, tt.index))
            for k, v in res.items():
                results.setdefault(variant, {}).setdefault(h, {})[k] = v
            y = tt["y"].values
            raw = np.mean((y >= p["p10"]) & (y <= p["p90"]))
            cal = np.mean((y >= p["p10"] - lo) & (y <= p["p90"] + hi))
            coverage.setdefault(f"{model_name}/{variant}", {})[h] = {"raw": float(raw), "calibrated": float(cal)}
        r = results["simulated_forecast"][h][model_name]
        print(f"{model_name:8s} h={h} sim NSE " + " ".join(f"{k}:{v['NSE']:.2f}" for k, v in r.items())
              + f"  dekning {coverage[f'{model_name}/simulated_forecast'][h]}", flush=True)

out = DATA / "eval"
out.mkdir(parents=True, exist_ok=True)
(out / "metrics_v2.json").write_text(json.dumps({"results": results, "coverage_p10_p90": coverage, "timing": timing,
                                                 "split": {"train_end": TRAIN_END, "val_end": VAL_END}}, indent=1))
MODELS.mkdir(parents=True, exist_ok=True)
(MODELS / "calibration.json").write_text(json.dumps(calibration, indent=1))
print(json.dumps(timing))
