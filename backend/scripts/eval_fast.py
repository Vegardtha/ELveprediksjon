"""Rask evaluering av modellvarianter på ekte arkiverte værprognoser, med rullerende opprinnelse.

Fire testperioder à et halvår fra 2025. For hver trenes modellen på alt før perioden (fasitvær før
prognosearkivet, ekte prognoser etter), med samme oppsett som i drift (fast antall trær, ingen early stopping).
Testradene har ekte prognoser for hele horisonten. Bare p50 og noen få horisonter, så én variant tar minutter.

Stasjonslista fryses til stasjonene i driftsmodellen, så tall fra ulike kjøringer kan sammenlignes mens nye
stasjoner hentes inn.

Metrikker per variant og horisont:
  RMSE     i log-vannføring på dager der elva steg (opp) eller falt (ned) mer enn 0.2 (ca. 20 %) over horisonten
  NSE      snitt av NSE per stasjon over alle testperiodene samlet (som i MODELL.md)
  dNSE     endring mot første variant per periode (snitt ± standardavvik over periodene)
  rec_bias median feil i log-vannføring (modell − fasit) i tørr resesjon etter flomtopp; > 0 er for treg nedgang
Skriver data/eval/fast_<navn>.json.

Eksempel: uv run python scripts/eval_fast.py --variants base,wx_fc,wx_fc_w5 --horizons 2,4,7
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import numpy as np
import pandas as pd

from elvepred import features
from elvepred.evaluation import nse
from elvepred.model.train import FC_MODEL, MODELS, N_ESTIMATORS, fit_quantile
from elvepred.settings import DATA

FOLDS = [("2025-01-01", "2025-07-01"), ("2025-07-01", "2026-01-01"), ("2026-01-01", "2026-07-01"),
         ("2026-07-01", "2100-01-01")]
SIG_UNTIL = FOLDS[0][0]  # feltsignaturer bare fra data før første testperiode
# valgfrie featuregrupper; base bruker ingen av dem
GROUPS = {
    "fc": ("wx_fc",),
    "dyn": ("dlq_max7", "days_since_max"),
    "sig": ("sig_rec", "sig_rec_hi", "sig_flash", "sig_lq_range", "sig_rec_loga", "sig_rec_b", "sig_q01"),
    "rec": ("rec_h", "rec_h_now"),
    "up": ("up_share", "up_rel0", "up_rel_anom", "up_dlq1", "up_dlq3", "up_dlq_now", "up_dlq_now6h"),
}

# variant: featuregrupper som brukes, vekt på rader med ekte prognose (w_fc), vekt på hendelser med regn,
# stigning eller fall (w_ev, bare fra features, ikke fra målet) og ekstra XGBoost-parametre
VARIANTS = {
    "base": dict(),
    "wx_fc": dict(groups=("fc",)),
    "wx_fc_w5": dict(groups=("fc",), w_fc=5),
    "wx_fc_w20": dict(groups=("fc",), w_fc=20),
    "dyn": dict(groups=("dyn",)),
    "sig": dict(groups=("sig",)),
    "sig_rec": dict(groups=("dyn", "sig", "rec")),
    "sig_rec_ev3": dict(groups=("dyn", "sig", "rec"), w_ev=3),
    "fc5_sig_rec": dict(groups=("fc", "dyn", "sig", "rec"), w_fc=5),
    "fc5_sig_rec_ev3": dict(groups=("fc", "dyn", "sig", "rec"), w_fc=5, w_ev=3),
    "fc2_sig_rec_ev3": dict(groups=("fc", "dyn", "sig", "rec"), w_fc=2, w_ev=3),
    "fc_sig_rec_ev3": dict(groups=("fc", "dyn", "sig", "rec"), w_ev=3),
    "fc2_sig_rec_ev3_up": dict(groups=("fc", "dyn", "sig", "rec", "up"), w_fc=2, w_ev=3),
    "trees1500": dict(params={"n_estimators": 1500}),
    "leaves63": dict(params={"max_leaves": 63}),
}
OPTIONAL = {c for g in GROUPS.values() for c in g}


def event(d: pd.DataFrame) -> np.ndarray:
    """Rader der elva er i bevegelse eller det er meldt mye regn – bestemt av features, ikke av fasit."""
    return ((d["rr_fsum"] >= 15) | (d["dlq1"].abs() >= 0.1) | (d["dlq_max7"] > -0.05) & (d["lq_max7"] - d["lq_mean30"] > 0.3)
            ).to_numpy()


p = argparse.ArgumentParser()
p.add_argument("--variants", default="base,wx_fc,wx_fc_w5,sig,wx_fc_w5_sig")
p.add_argument("--horizons", default="2,4,7")
p.add_argument("--name", default="latest")
args = p.parse_args()
variants = args.variants.split(",")
horizons = [int(h) for h in args.horizons.split(",")]
stations = joblib.load(MODELS / "h1_p50.joblib")["stations"]


def rec_mask(d: pd.DataFrame, h: int) -> np.ndarray:
    """Tørr resesjon etter flomtopp: fallende, langt over 30-døgnsnittet og lite nedbør i prognosen."""
    return ((d["dlq1"] < -0.05) & (d["lq_max7"] - d["lq_mean30"] > 0.7) & (d["rr_fsum"] < 2 * h)).to_numpy()


results = {}
for h in horizons:
    t0 = time.perf_counter()
    mixed = features.dataset(stations, h, "wx_mixed", fc_model=FC_MODEL, sig_until=SIG_UNTIL, upstream=True)
    real = features.dataset(stations, h, "wx_fc", fc_model=FC_MODEL, sig_until=SIG_UNTIL, upstream=True)
    assert (mixed["date"].values == real["date"].values).all()
    print(f"h={h}: {len(mixed)} rader ({time.perf_counter() - t0:.0f}s)", flush=True)
    target_date = mixed["date"] + pd.Timedelta(days=h)
    pred = {v: np.full(len(real), np.nan) for v in variants}
    in_test = np.zeros(len(real), bool)
    fold_of = np.full(len(real), -1)
    for i, (a, b) in enumerate(FOLDS):
        tr = (target_date < a).to_numpy()  # målet må ligge før testperioden
        te = ((real["date"] >= a) & (real["date"] < b) & real["rr_fsum"].notna()).to_numpy()
        if not te.any():
            continue
        in_test |= te
        fold_of[te] = i
        for v in variants:
            cfg = VARIANTS[v]
            use = {c for g in cfg.get("groups", ()) for c in GROUPS[g]}
            cols = [c for c in mixed.columns if c not in features.NON_FEATURES and (c not in OPTIONAL or c in use)]
            weight = ((1 + (cfg.get("w_fc", 1) - 1) * mixed.loc[tr, "wx_fc"].to_numpy())
                      * (1 + (cfg.get("w_ev", 1) - 1) * event(mixed[tr])))
            extra = dict(cfg.get("params", {}))
            n = extra.pop("n_estimators", N_ESTIMATORS)
            t1 = time.perf_counter()
            m = fit_quantile(mixed.loc[tr, cols], mixed.loc[tr, "y"], 0.5, n, sample_weight=weight, **extra)
            pred[v][te] = m.predict(real.loc[te, cols])
            print(f"  periode {a}: {v:14s} trent på {tr.sum()} rader ({(mixed.loc[tr, 'wx_fc'] > 0).sum()} med prognose),"
                  f" test {te.sum()} ({time.perf_counter() - t1:.0f}s)", flush=True)

    t = real[in_test].reset_index(drop=True)
    rec = rec_mask(t, h)
    lys = rec & (t["station"] == "7.29.0").to_numpy()
    res = {}
    for v in variants:
        yhat = pred[v][in_test]
        qhat = np.expm1(t["lq0"].to_numpy() + yhat)
        per_st = {st: nse(g["q_true"].to_numpy(), qhat[g.index])
                  for st, g in t.groupby("station", observed=True)}
        per_fold = []
        for i in range(len(FOLDS)):
            s = fold_of[in_test] == i
            if s.any():
                per_fold.append(float(np.mean([nse(g["q_true"].to_numpy(), qhat[g.index])
                                               for _, g in t[s].groupby("station", observed=True)])))
        err = yhat - t["y"].to_numpy()
        y = t["y"].to_numpy()
        rmse = lambda s: float(np.sqrt(np.mean(err[s] ** 2)))
        res[v] = {"NSE": float(np.mean(list(per_st.values()))), "NSE_fold": per_fold,
                  "rmse_rise": rmse(y > 0.2), "rmse_fall": rmse(y < -0.2), "rmse_all": rmse(np.ones_like(y, bool)),
                  "rec_bias": float(np.median(err[rec])), "rec_n": int(rec.sum()),
                  "lysaker_rec_bias": float(np.median(err[lys])) if lys.any() else None,
                  "per_station": {str(k): float(x) for k, x in per_st.items()}}
    base = res[variants[0]]["NSE_fold"]
    for v in variants:
        d = np.array(res[v]["NSE_fold"]) - np.array(base)
        res[v]["dNSE"] = [float(d.mean()), float(d.std())]
        print(f"h={h} {v:14s} NSE {res[v]['NSE']:.3f}  dNSE {d.mean():+.3f} ± {d.std():.3f}  "
              f"perioder {' '.join(f'{x:.3f}' for x in res[v]['NSE_fold'])}  RMSE opp {res[v]['rmse_rise']:.3f} "
              f"ned {res[v]['rmse_fall']:.3f}  rec_bias {res[v]['rec_bias']:+.3f} "
              f"(Lysaker {res[v]['lysaker_rec_bias']})", flush=True)
    results[h] = res

out = DATA / "eval"
out.mkdir(parents=True, exist_ok=True)
(out / f"fast_{args.name}.json").write_text(json.dumps({"folds": FOLDS, "stations": list(stations), "results": results},
                                                       indent=1))
