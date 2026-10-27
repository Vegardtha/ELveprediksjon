"""Evaluering på ekte arkiverte værprognoser (Open-Meteo Previous Runs, fra mars 2024).

Trening ..2024-10 (fasitvær før mars 2024, ekte prognoser etter for «mixed»),
validering + kalibrering 2024-11..2025-06, test 2025-07..i dag. Alle modeller bruker nowcast.

Modeller:
  gts        dagens oppsett (GTS-vær + HBV-prognose). Kan bare testes med fasit/simulert feil.
  wx_perf    nedbør/temp framover, trent på fasitvær.
  wx_mixed   nedbør/temp framover, trent på fasit før arkivet og ekte prognoser etter.
Alle testes på de samme radene (der prognosearkivet har data for horisonten).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from elvepred import features
from elvepred.evaluation import fit_lgb, perturb_gts, perturb_wx, scores, stations
from elvepred.model.train import FC_MODEL, MODELS, WEATHER
from elvepred.settings import DATA

TRAIN_END, VAL_END = "2024-10-31", "2025-06-30"
p = argparse.ArgumentParser()
p.add_argument("--fc-models", default="ecmwf_ifs025,metno_seamless")
p.add_argument("--skip-gts", action="store_true")
args = p.parse_args()
FC_MODELS = args.fc_models.split(",")

st_list = list(stations)
results, coverage, calibration, timing = {}, {}, {}, {}
for h in features.HORIZONS:
    t0 = time.perf_counter()
    ds = {"gts": features.dataset(st_list, h, "gts"), "wx_perfect": features.dataset(st_list, h, "wx_perfect")}
    for fm in FC_MODELS:
        ds[f"wx_fc/{fm}"] = features.dataset(st_list, h, "wx_fc", fc_model=fm)
        ds[f"wx_mixed/{fm}"] = features.dataset(st_list, h, "wx_mixed", fc_model=fm)
    base = ds["gts"]
    for k, d in ds.items():
        assert (d["date"].values == base["date"].values).all() and (d["station"].values == base["station"].values).all(), k
    date = base["date"]
    tr, va, te = date <= TRAIN_END, (date > TRAIN_END) & (date <= VAL_END), date > VAL_END
    has_fc = np.logical_and.reduce([ds[f"wx_fc/{fm}"]["rr_fsum"].notna().values for fm in FC_MODELS])
    va, te = va & has_fc, te & has_fc
    res = {}

    def evaluate(name, models, cols, test_sets, calib_set):
        pv = {n: m.predict(calib_set[cols]) for n, m in models.items()}
        lo = float(np.quantile(pv["p10"] - calib_set["y"].values, 0.9))
        hi = float(np.quantile(calib_set["y"].values - pv["p90"], 0.9))
        calibration.setdefault(name, {})[h] = {"p10": lo, "p90": hi}
        for variant, tt in test_sets.items():
            pp = {n: m.predict(tt[cols]) for n, m in models.items()}
            res[f"{name} | {variant}"] = scores(tt, pd.Series(np.expm1(tt["lq0"].values + pp["p50"]), tt.index))
            y = tt["y"].values
            coverage.setdefault(f"{name} | {variant}", {})[h] = {
                "raw": float(np.mean((y >= pp["p10"]) & (y <= pp["p90"]))),
                "calibrated": float(np.mean((y >= pp["p10"] - lo) & (y <= pp["p90"] + hi)))}

    cols_of = lambda d: [c for c in d.columns if c not in features.NON_FEATURES]
    rng = lambda s: np.random.default_rng(1000 * h + s)

    # Baseline: siste timesmåling holdes konstant
    t_ = base[te]
    res["persistence_now"] = scores(t_, pd.Series(np.expm1(t_["lq_now"].fillna(t_["lq0"])).values, t_.index))

    if not args.skip_gts:
        d = ds["gts"]
        m = fit_lgb(d[tr], d[va], cols_of(d))
        evaluate("gts", m, cols_of(d), {"perfect": d[te], "simulated": perturb_gts(d[te], h, rng(1))},
                 perturb_gts(d[va], h, rng(2)))

    d = ds["wx_perfect"]
    m = fit_lgb(d[tr], d[va], cols_of(d))
    tests = {"perfect": d[te], "simulated": perturb_wx(d[te], h, rng(3))}
    tests.update({f"real {fm}": ds[f"wx_fc/{fm}"][te] for fm in FC_MODELS})
    evaluate("wx_perf", m, cols_of(d), tests, ds[f"wx_fc/{FC_MODELS[0]}"][va])

    for fm in FC_MODELS:
        d = ds[f"wx_mixed/{fm}"]
        m = fit_lgb(d[tr], d[va], cols_of(d))
        evaluate(f"wx_mixed/{fm}", m, cols_of(d), {f"real {fm}": ds[f"wx_fc/{fm}"][te]}, ds[f"wx_fc/{fm}"][va])

    results[h] = res
    timing[h] = time.perf_counter() - t0
    nse = lambda r: np.mean([v["NSE"] for v in r.values()])
    print(f"h={h} n_test={int(te.sum())} ({timing[h]:.0f}s)  " +
          "  ".join(f"{k}: {nse(v):.2f}" for k, v in res.items()), flush=True)

out = DATA / "eval"
out.mkdir(parents=True, exist_ok=True)
(out / "metrics_fc.json").write_text(json.dumps({
    "results": results, "coverage_p10_p90": coverage, "calibration": calibration, "timing_s": timing,
    "split": {"train_end": TRAIN_END, "val_end": VAL_END}, "fc_models": FC_MODELS}, indent=1))

# Kalibrering for driftsoppsettet brukes av predict.py
prod = f"{WEATHER}/{FC_MODEL}"
if prod in calibration:
    MODELS.mkdir(parents=True, exist_ok=True)
    (MODELS / "calibration.json").write_text(json.dumps(calibration[prod], indent=1))
