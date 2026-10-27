"""Timesprognose 1–48 timer fram, fra siste timesmåling (utstedelsestid T, UTC).

Én felles LightGBM-modell per kvantil der horisonten k (timer) er en feature, og målet er
y = log1p(q[T+k]) - log1p(q[T]). Vær kommer fra MET Nordic-prognoser per time (Open-Meteo),
så treningen er begrenset til prognosearkivet (fra mars 2024).

Ledetid i arkivet: for en time på dato T.date + d brukes kjøringen fra dag d (+1 hvis T er før
kl. 12 UTC, siden dagens kjøringer da stort sett ikke finnes ennå). Timer før T bruker ledetid 0
(nær analyse) som stand-in for observert nedbør.
"""
import numpy as np
import pandas as pd

from elvepred.settings import DATA

PAST = 72  # timer historikk i nedbørvinduet
MAX_K = 48
K_TRAIN = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 21, 24, 28, 32, 36, 40, 44, 48]
ISSUE_STEP = 3  # timer mellom utstedelser i trening
NON_FEATURES = ("time", "y", "q0", "q_true")
GTS_COLS = ("swe", "gwb_sssrel", "gwb_q")


def load(station: str) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    q = pd.read_parquet(DATA / "raw" / "hydapi_hourly" / f"{station}.parquet")["q"]
    fc = pd.read_parquet(DATA / "raw" / "forecasts" / "metno_seamless" / f"{station}_hourly.parquet")
    g = pd.read_parquet(DATA / "raw" / "gts" / f"{station}.parquet")
    return q, fc, g


def _window(a: np.ndarray, idx: np.ndarray, lead: np.ndarray) -> np.ndarray:
    out = np.full(idx.shape, np.nan)
    ok = (idx >= 0) & (idx < len(a))
    out[ok] = a[idx[ok], lead[ok]]
    return out


def build(q: pd.Series, fc: pd.DataFrame, g: pd.DataFrame, issues: pd.DatetimeIndex, ks=K_TRAIN,
          with_target: bool = True) -> pd.DataFrame:
    """Én rad per (utstedelse, k). q er timesserie, fc har rr_l{N}/tm_l{N}, g er GTS per døgn."""
    start = issues.min() - pd.Timedelta(hours=PAST + 48)
    end = issues.max() + pd.Timedelta(hours=MAX_K)
    grid = pd.date_range(start.floor("h"), end.ceil("h"), freq="h")
    Q = q.reindex(grid).to_numpy(dtype=float)
    fcg = fc.reindex(grid)
    RR = fcg[[f"rr_l{n}" for n in range(8)]].to_numpy(dtype=float)
    TM = fcg[[f"tm_l{n}" for n in range(8)]].to_numpy(dtype=float)
    days = ((grid - grid[0].normalize()) // pd.Timedelta(days=1)).to_numpy()

    i = grid.get_indexer(issues)
    off = np.arange(-PAST + 1, MAX_K + 1)  # timer (T-71 .. T+48]
    idx = i[:, None] + off[None, :]
    d = days[np.clip(idx, 0, len(grid) - 1)] - days[i][:, None]
    early = np.asarray(issues.hour < 12)[:, None].astype(int)
    lead = np.where(off[None, :] <= 0, 0, np.clip(d + early, 0, 7))
    rr = _window(RR, idx, lead)
    tm = _window(TM, idx, lead)
    C = np.concatenate([np.zeros((len(i), 1)), np.cumsum(np.nan_to_num(rr), axis=1)], axis=1)
    nan_c = np.concatenate([np.zeros((len(i), 1)), np.cumsum(np.isnan(rr), axis=1)], axis=1)
    T_c = np.concatenate([np.zeros((len(i), 1)), np.cumsum(np.nan_to_num(tm), axis=1)], axis=1)
    p0 = PAST  # kolonne for offset 0 er p0-1, så sum over (a, b] = C[p0+b] - C[p0+a]

    def s(a, b, M=C):
        return M[:, p0 + b] - M[:, p0 + a]

    lq = np.log1p(Q)
    lqs = pd.Series(lq, index=grid)
    base = pd.DataFrame({
        "time": issues,
        "lq_now": lq[i],
        **{f"dlq{h}h": lq[i] - lq[i - h] for h in (1, 3, 6, 12, 24, 48)},
        "lq_max24": lqs.rolling(24, min_periods=12).max().to_numpy()[i],
        "lq_min24": lqs.rolling(24, min_periods=12).min().to_numpy()[i],
        "lq_mean72": lqs.rolling(72, min_periods=36).mean().to_numpy()[i],
        "rr_p6": s(-6, 0), "rr_p24": s(-24, 0), "rr_p72": s(-PAST, 0),
        "tm_now": tm[:, p0 - 1],
        "hour": np.asarray(issues.hour),
        "doy_sin": np.sin(2 * np.pi * issues.dayofyear / 365.25),
        "doy_cos": np.cos(2 * np.pi * issues.dayofyear / 365.25),
    })
    # GTS-tilstand fra forrige døgn (døgnet stemples på slutten, dagens er ikke ferdig)
    gd = g[list(GTS_COLS)].reindex(issues.normalize() - pd.Timedelta(days=1))
    for c in GTS_COLS:
        base[c] = gd[c].to_numpy()
    base["lgwb_q"] = np.log1p(base.pop("gwb_q"))

    rows = []
    for k in ks:
        f = base.copy()
        f["k"] = k
        f["rr_f"] = s(0, k)
        f["rr_k6"] = s(k - 6, k)
        f["rr_k12"] = s(k - 12, k)
        f["rr_k24"] = s(k - 24, k)
        f["rr_fmax"] = np.nanmax(np.where(np.arange(MAX_K)[None, :] < k, rr[:, p0:p0 + MAX_K], np.nan), axis=1)
        f["tm_f"] = s(0, k, T_c) / k
        f["hour_k_sin"] = np.sin(2 * np.pi * (f["hour"] + k) / 24)
        f["hour_k_cos"] = np.cos(2 * np.pi * (f["hour"] + k) / 24)
        f["fc_missing"] = s(0, k, nan_c)
        if with_target:
            f["q0"] = Q[i]
            f["q_true"] = Q[i + k]
            f["y"] = np.log1p(f["q_true"]) - f["lq_now"]
        rows.append(f)
    out = pd.concat(rows, ignore_index=True)
    out = out[out["fc_missing"] == 0].drop(columns="fc_missing")
    return out.dropna(subset=["lq_now", "y"] if with_target else ["lq_now"])


def dataset(stations: list[str]) -> pd.DataFrame:
    parts = []
    for st in stations:
        q, fc, g = load(st)
        t0 = max(fc.index.min() + pd.Timedelta(hours=PAST + 48), q.dropna().index.min() + pd.Timedelta(hours=72))
        t1 = min(fc.index.max(), q.dropna().index.max()) - pd.Timedelta(hours=1)
        issues = pd.date_range(t0.ceil("D"), t1, freq=f"{ISSUE_STEP}h")
        issues = issues[q.reindex(issues).notna().to_numpy()]
        d = build(q, fc, g, issues)
        d["station"] = st
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["station"] = pd.Categorical(d["station"], categories=stations)
    return d
