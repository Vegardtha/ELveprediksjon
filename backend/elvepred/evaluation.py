"""Felles hjelpere for evalueringsskriptene: metrikker, modelltilpasning og simulert prognosefeil."""
import numpy as np
import pandas as pd

from elvepred import classify
from elvepred.model.train import QUANTILES, fit_quantile
from elvepred.settings import load_stations

stations = {r["station"]: r for r in load_stations()}


def nse(o, s):
    return 1 - np.sum((s - o) ** 2) / np.sum((o - o.mean()) ** 2)


def f1(true, pred):
    tp = np.sum(true & pred)
    p, r = tp / max(pred.sum(), 1), tp / max(true.sum(), 1)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def scores(d: pd.DataFrame, qhat: pd.Series) -> dict:
    out = {}
    for st, g in d.groupby("station", observed=True):
        t = stations[st]["thresholds"]
        o, s = g["q_true"].values, qhat.loc[g.index].values
        ci = np.array([classify.interval(x, t) for x in o])
        cs = np.array([classify.interval(x, t) for x in s])
        out[stations[st]["id"]] = {
            "n": len(g), "NSE": nse(o, s), "MAE": float(np.mean(np.abs(o - s))),
            "class_acc": float(np.mean(ci == cs)),
            "F1_paddleable": f1((o >= t["minimum"]) & (o < t["maximum"]), (s >= t["minimum"]) & (s < t["maximum"])),
            "F1_optimal": f1((o >= t["optimum"]) & (o < t["maximum"]), (s >= t["optimum"]) & (s < t["maximum"])),
        }
    return out


def fit_models(tr: pd.DataFrame, va: pd.DataFrame, cols: list[str]) -> dict:
    """p10/p50/p90-modeller med early stopping på valideringssettet."""
    return {name: fit_quantile(tr[cols], tr["y"], a, 3000, eval_set=[(va[cols], va["y"])], early_stopping=100)
            for name, a in QUANTILES.items()}


def _noisy_rain(te: pd.DataFrame, h: int, rng) -> pd.Series:
    """Lognormal feil på døgnnedbør (σ øker med ledetid). Returnerer forholdet ny/gammel sum."""
    for k in range(1, h + 1):
        te[f"rr_f{k}"] = te[f"rr_f{k}"] * np.exp(rng.normal(0, 0.35 + 0.12 * k, len(te)))
    tot = te[[f"rr_f{k}" for k in range(1, h + 1)]].sum(axis=1)
    ratio = (tot / te["rr_fsum"].replace(0, np.nan)).fillna(1.0).clip(0.1, 10)
    te["rr_fsum"] = tot
    return ratio


def perturb_gts(te: pd.DataFrame, h: int, rng) -> pd.DataFrame:
    """Simulert prognosefeil for GTS-features, inkl. HBV-prognosen (drives av samme vær)."""
    te = te.copy()
    ratio = _noisy_rain(te, h, rng)
    te["qtt_fsum"] = te["qtt_fsum"] * ratio
    te["tm_fmean"] = te["tm_fmean"] + rng.normal(0, 0.8 + 0.25 * h, len(te))
    hbv_fac = np.exp(rng.normal(0, 0.06 * h, len(te))) * ratio ** 0.3
    te["hbv_fh"] = te["hbv_fh"] * hbv_fac
    te["hbv_fsum"] = te["hbv_fsum"] * hbv_fac
    te["dlhbv_f"] = np.log1p(te["hbv_fh"]) - np.log1p(te["hbv0"])
    return te


def perturb_wx(te: pd.DataFrame, h: int, rng) -> pd.DataFrame:
    """Samme simulerte feil som perturb_gts, for features med bare nedbør/temperatur."""
    te = te.copy()
    ratio = _noisy_rain(te, h, rng)
    te["rr_fmax"] = te[[f"rr_f{k}" for k in range(1, h + 1)]].max(axis=1)
    te["rain_fsum"] = te["rain_fsum"] * ratio
    dt = rng.normal(0, 0.8 + 0.25 * h, len(te))
    te["tm_fmean"] = te["tm_fmean"] + dt
    te["tm_f1"] = te["tm_f1"] + rng.normal(0, 0.8, len(te))
    te["pdd_fsum"] = (te["pdd_fsum"] + dt * h).clip(lower=0)
    return te
