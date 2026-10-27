"""Tester hvordan døgnprognosen etter 48 t best knyttes til slutten av timesprognosen.

Døgnmodellen er forankret i gårsdagens døgnmiddel og henger etter etter flomtopper; timesmodellen
starter fra siste timesmåling. Korreksjon i log-rom: δ = timesmodellens nivå ved T+45 t minus
døgnmodellens (interpolert) nivå samme tid, lagt til døgn h med vekt exp(-(h - x)/τ).
Begge modeller trenes på data til og med 2025-06-30 og testes etter (bare p50).
Skriver data/eval/blend.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lightgbm as lgb
import numpy as np
import pandas as pd

from elvepred import features, hourly
from elvepred.evaluation import nse
from elvepred.model.train import FC_MODEL, N_ESTIMATORS, PARAMS, WEATHER
from elvepred.settings import DATA, load_rivers

SPLIT = "2025-06-30"
TAUS = [0, 1, 2, 4, 8, np.inf]
ANCHOR_K = range(42, 49)  # snitt over siste 7 timer, sentrert i T+45 t
CHECK_K = [12, 24, 36, 48]  # timer der timesmodellen trekkes mot døgnmodellen
ALPHAS = [0, 0.25, 0.5, 0.75, 1]

stations = [r["station"] for r in load_rivers()]
ids = {r["station"]: r["id"] for r in load_rivers()}

# Døgnmodell p50 for h=2..9
daily = None
for h in range(1, 10):
    d = features.dataset(stations, h, WEATHER, fc_model=FC_MODEL)
    cols = [c for c in d.columns if c not in features.NON_FEATURES]
    tr, te = d[d.date <= SPLIT], d[d.date > SPLIT]
    m = lgb.LGBMRegressor(objective="quantile", alpha=0.5, n_estimators=N_ESTIMATORS, **PARAMS)
    m.fit(tr[cols], tr["y"], categorical_feature=["station"])
    p = te[["station", "date", "hour", "lq0"]].copy()
    p[f"lp{h}"] = p["lq0"] + m.predict(te[cols])
    p[f"lq{h}"] = np.log1p(te["q_true"])
    p = p.drop(columns="lq0")
    daily = p if daily is None else daily.merge(p, on=["station", "date", "hour"], how="inner")
    print(f"døgn h={h}: {len(te)} testrader", flush=True)

# Timesmodell p50
hd = hourly.dataset(stations)
hcols = [c for c in hd.columns if c not in hourly.NON_FEATURES]
hm = lgb.LGBMRegressor(objective="quantile", alpha=0.5, n_estimators=800, **PARAMS)
hm.fit(hd.loc[hd.time <= SPLIT, hcols], hd.loc[hd.time <= SPLIT, "y"], categorical_feature=["station"])
print("timesmodell trent", flush=True)

anchors = []
for st in stations:
    q, fc, g = hourly.load(st)
    sub = daily[daily.station == st]
    issues = pd.DatetimeIndex(sub["date"] + pd.Timedelta(days=1) + pd.to_timedelta(sub["hour"], unit="h"))
    issues = issues[(issues > fc.index.min() + pd.Timedelta(days=6)) & (issues < fc.index.max() - pd.Timedelta(days=3))]
    issues = issues[q.reindex(issues).notna().to_numpy()].unique()
    X = hourly.build(q, fc, g, issues, ks=list(ANCHOR_K) + CHECK_K, with_target=False)
    X["station"] = pd.Categorical([st] * len(X), categories=stations)
    X["lp"] = X["lq_now"] + hm.predict(X[hcols])
    a = X[X.k.isin(ANCHOR_K)].groupby("time")["lp"].mean().rename("anchor").reset_index()
    for k in CHECK_K:
        xk = X[X.k == k].groupby("time")[["lp"]].mean()
        a[f"hk{k}"] = xk["lp"].reindex(a["time"]).to_numpy()
        a[f"tk{k}"] = np.log1p(q.reindex(a["time"] + pd.Timedelta(hours=k)).to_numpy())
    a["station"] = st
    anchors.append(a)
anchors = pd.concat(anchors)
daily["time"] = daily["date"] + pd.Timedelta(days=1) + pd.to_timedelta(daily["hour"], unit="h")
daily["station"] = daily["station"].astype(str)
b = daily.merge(anchors, on=["station", "time"], how="inner")
print(f"{len(b)} utstedelser med begge modeller", flush=True)

# Døgnmodellens nivå ved T+45 t: x døgn etter t, døgn h plottes kl. 12
x = (b["hour"].to_numpy() + 24 + 45 - 12) / 24
lo = np.floor(x).astype(int)
w = x - lo
lp = {h: b[f"lp{h}"].to_numpy() for h in range(1, 10)}
interp = np.array([(1 - wi) * lp[l][i] + wi * lp[min(l + 1, 9)][i] for i, (l, wi) in enumerate(zip(lo, w))])
delta = b["anchor"].to_numpy() - interp
end = x + 3 / 24  # T+48 t
print(f"δ: median {np.median(delta):.3f}, |δ| median {np.median(np.abs(delta)):.3f}")

out = {}
for h in range(3, 10):
    s = h > end  # bare døgn som ligger etter timesvinduet
    res = {}
    for tau in TAUS:
        wgt = 0.0 if tau == 0 else (1.0 if np.isinf(tau) else np.exp(-(h - x[s]) / tau))
        pred = np.expm1(lp[h][s] + wgt * delta[s])
        obs = np.expm1(b[f"lq{h}"].to_numpy()[s])
        st = b["station"].to_numpy()[s]
        res[str(tau)] = float(np.mean([nse(obs[st == k], pred[st == k]) for k in np.unique(st)]))
    out[h] = res
    print(f"h={h} (n={s.sum()}): " + "  ".join(f"τ={t}: {v:.3f}" for t, v in res.items()), flush=True)
big = np.abs(delta) > 0.2
print(f"store avvik (|δ| > 0.2): {big.sum()} av {len(delta)}")
for h in range(3, 10):
    s = (h > end) & big
    res = {}
    for tau in TAUS:
        wgt = 0.0 if tau == 0 else (1.0 if np.isinf(tau) else np.exp(-(h - x[s]) / tau))
        pred = np.expm1(lp[h][s] + wgt * delta[s])
        obs = np.expm1(b[f"lq{h}"].to_numpy()[s])
        res[str(tau)] = float(np.sqrt(np.mean((np.log1p(pred) - np.log1p(obs)) ** 2)))
    print(f"  h={h} RMSE(log) (n={s.sum()}): " + "  ".join(f"τ={t}: {v:.3f}" for t, v in res.items()), flush=True)

# Motsatt retning: trekk timesmodellen mot døgnmodellens (interpolerte) bane
hour = b["hour"].to_numpy()
allh = np.array([lp[h] for h in range(1, 10)])  # (9, n)
for k in CHECK_K:
    xk = (hour + 24 + k - 12) / 24
    dk = np.array([np.interp(xi, range(1, 10), allh[:, i]) for i, xi in enumerate(xk)])
    hk, tk = b[f"hk{k}"].to_numpy(), b[f"tk{k}"].to_numpy()
    ok = ~np.isnan(tk) & ~np.isnan(hk)
    st = b["station"].to_numpy()
    res = {}
    for a in ALPHAS:
        pred, obs = np.expm1((1 - a) * hk + a * dk)[ok], np.expm1(tk)[ok]
        res[a] = float(np.mean([nse(obs[st[ok] == s_], pred[st[ok] == s_]) for s_ in np.unique(st[ok])]))
    out[f"hourly_k{k}"] = res
    print(f"time k={k}: " + "  ".join(f"α={a}: {v:.3f}" for a, v in res.items()), flush=True)
(DATA / "eval" / "blend.json").write_text(json.dumps(out, indent=1))
