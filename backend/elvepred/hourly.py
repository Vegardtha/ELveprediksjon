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

from elvepred import features
from elvepred.settings import DATA

PAST = 72  # timer historikk i nedbørvinduet
MAX_K = 48
K_TRAIN = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 21, 24, 28, 32, 36, 40, 44, 48]
ISSUE_STEP = 3  # timer mellom utstedelser i trening
NON_FEATURES = ("time", "y", "q0", "q_true")
GTS_COLS = ("swe", "gwb_sssrel", "gwb_q")
# Historikk før prognosearkivet: utstedelser rundt kraftige nedbørsdøgn (seNorge), med fasitvær per time fra
# seNorge-døgnnedbøren fordelt etter ERA5 (`truth_weather`). Utvalget bestemmes av nedbøren, som er en feature,
# ikke av vannføringen, så modellen ikke lærer at kraftig regn alltid gir flom.
HISTORY_START = "1990-01-01"
WET_MM, WET_QUANTILE = 15.0, 0.99  # våte døgn: nedbør ≥ max(15 mm, 99-persentilen for stasjonen)
WET_ISSUES = (-2, 1)  # utstedelsesdager rundt et vått døgn (døgn d dekker 06 UTC d-1 til 06 UTC d)
ERA5_PAD = (-5, 1)  # ERA5 trengs også for nedbørvinduet før (72 t) og etter (48 t) utstedelsene


def load(station: str) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    q = pd.read_parquet(DATA / "raw" / "hydapi_hourly" / f"{station}.parquet")["q"]
    fc = pd.read_parquet(DATA / "raw" / "forecasts" / "metno_seamless" / f"{station}_hourly.parquet")
    g = pd.read_parquet(DATA / "raw" / "gts" / f"{station}.parquet")
    return q, fc, g


def wet_days(g: pd.DataFrame, start: pd.Timestamp, end: str = "2024-03-01") -> pd.DatetimeIndex:
    """seNorge-døgn med kraftig nedbør mellom start og prognosearkivets start."""
    r = g.loc[(g.index >= start) & (g.index < end), "rr"]
    return r.index[r >= max(WET_MM, r.quantile(WET_QUANTILE))]


def era5_ranges(wet: pd.DatetimeIndex, max_gap: int = 14) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Datoperioder med ERA5 som trengs rundt de våte døgnene. Perioder med under max_gap døgn mellom slås sammen,
    siden kvoten regnes per påbegynte 14 døgn og hvert kall tar ~30 s."""
    out = []
    for d in wet.sort_values():
        a, b = d + pd.Timedelta(days=WET_ISSUES[0] + ERA5_PAD[0]), d + pd.Timedelta(days=WET_ISSUES[1] + ERA5_PAD[1] + 2)
        if out and (a - out[-1][1]).days <= max_gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def truth_weather(station: str, g: pd.DataFrame) -> pd.DataFrame | None:
    """Fasitvær per time i samme format som prognosearkivet (rr_l{N}/tm_l{N}, like for alle ledetider).

    seNorge-døgnnedbøren (døgn d = 06 UTC d-1 til 06 UTC d) fordeles på timene etter ERA5 samme døgn, så
    døgnsummene er de samme som døgnmodellen ser. Er ERA5 nesten tørr mens seNorge har nedbør, fordeles den jevnt.
    Temperaturen er ERA5 forskjøvet så døgnsnittet blir seNorge-temperaturen. None uten ERA5-fil."""
    f = DATA / "raw" / "era5" / f"{station}.parquet"
    if not f.exists():
        return None
    e = pd.read_parquet(f).astype(float)
    if e.empty:
        return None
    # timesverdien gjelder timen før tidsstempelet: kl. 07–23 hører til neste seNorge-døgn, kl. 00–06 til samme
    day = (e.index - pd.Timedelta(hours=7)).normalize() + pd.Timedelta(days=1)
    grp = e.groupby(day)
    n, rsum, tmean = grp["rr"].count(), grp["rr"].sum(), grp["tm"].mean()
    full = n.index[n == 24]
    ok = day.isin(full)
    e, day = e[ok], day[ok]
    rd = g["rr"].reindex(day).to_numpy()
    s = rsum.reindex(day).to_numpy()
    w = np.where(s >= 0.1, e["rr"].to_numpy() / np.where(s > 0, s, 1), 1 / 24)
    rr = rd * w
    tm = e["tm"].to_numpy() + (g["tm"].reindex(day).to_numpy() - tmean.reindex(day).to_numpy())
    out = pd.DataFrame({**{f"rr_l{n}": rr for n in range(8)}, **{f"tm_l{n}": tm for n in range(8)}}, index=e.index)
    return out.dropna()


def _window(a: np.ndarray, idx: np.ndarray, lead: np.ndarray) -> np.ndarray:
    out = np.full(idx.shape, np.nan)
    ok = (idx >= 0) & (idx < len(a))
    out[ok] = a[idx[ok], lead[ok]]
    return out


def build(q: pd.Series, fc: pd.DataFrame, g: pd.DataFrame, issues: pd.DatetimeIndex, ks=K_TRAIN,
          with_target: bool = True, sig: dict | None = None, wx_fc: float = 1.0) -> pd.DataFrame:
    """Én rad per (utstedelse, k). q er timesserie, fc har rr_l{N}/tm_l{N}, g er GTS per døgn.

    wx_fc: 1 når været er en ekte prognose (alltid i drift), 0 for fasitvær (`truth_weather`).

    sig: feltsignatur (features.signature) gir faste kolonner og `rec_k`, fallet de neste k timene hvis det er tørt."""
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
        # avstand til og tid siden siste topp (72 t): skiller stigning, topp og tidlig/sen resesjon
        "dlq_max72": lq[i] - lqs.rolling(72, min_periods=36).max().to_numpy()[i],
        "h_since_max72": lqs.rolling(72, min_periods=36).apply(lambda x: len(x) - 1 - np.nanargmax(x), raw=True)
        .to_numpy()[i],
        "lq_min24": lqs.rolling(24, min_periods=12).min().to_numpy()[i],
        "lq_mean72": lqs.rolling(72, min_periods=36).mean().to_numpy()[i],
        "rr_p6": s(-6, 0), "rr_p24": s(-24, 0), "rr_p72": s(-PAST, 0),
        "tm_now": tm[:, p0 - 1],
        "hour": np.asarray(issues.hour),
        "wx_fc": wx_fc,
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
        if sig:
            for c, v in sig.items():
                f[c] = v
            f["rec_k"] = features.recession(np.expm1(f["lq_now"].to_numpy()), k / 24, sig)
        if with_target:
            f["q0"] = Q[i]
            f["q_true"] = Q[i + k]
            f["y"] = np.log1p(f["q_true"]) - f["lq_now"]
        rows.append(f)
    out = pd.concat(rows, ignore_index=True)
    out = out[out["fc_missing"] == 0].drop(columns="fc_missing")
    return out.dropna(subset=["lq_now", "y"] if with_target else ["lq_now"])


def dataset(stations: list[str], sigs: dict[str, dict] | None = None, history: bool = False) -> pd.DataFrame:
    """sigs: feltsignatur per stasjon (features.signature), eller None for å utelate signaturfeaturene.

    history: ta også med utstedelser rundt kraftige nedbørsdøgn før prognosearkivet, med fasitvær
    (`truth_weather`, wx_fc = 0), for stasjonene der ERA5 er hentet."""
    parts = []
    for st in stations:
        q, fc, g = load(st)
        sig = (sigs or {}).get(st)
        t0 = max(fc.index.min() + pd.Timedelta(hours=PAST + 48), q.dropna().index.min() + pd.Timedelta(hours=72))
        t1 = min(fc.index.max(), q.dropna().index.max()) - pd.Timedelta(hours=1)
        issues = pd.date_range(t0.ceil("D"), t1, freq=f"{ISSUE_STEP}h")
        issues = issues[q.reindex(issues).notna().to_numpy()]
        d = build(q, fc, g, issues, sig=sig)
        if history and (tw := truth_weather(st, g)) is not None:
            start = max(q.dropna().index.min() + pd.Timedelta(hours=72), pd.Timestamp(HISTORY_START))
            days = pd.DatetimeIndex(sorted({w + pd.Timedelta(days=k) for w in wet_days(g, start)
                                            for k in range(WET_ISSUES[0], WET_ISSUES[1] + 1)}))
            hi = (days.to_numpy()[:, None] + pd.to_timedelta(np.arange(0, 24, ISSUE_STEP), unit="h").to_numpy()[None, :]).ravel()
            hi = pd.DatetimeIndex(hi)
            hi = hi[(hi < t0) & (hi >= start) & q.reindex(hi).notna().to_numpy()]
            # hele nedbørvinduet (72 t før, 48 t etter) må ha fasitvær, ellers telles hull som tørt
            have = tw["rr_l0"].reindex(pd.date_range(hi.min() - pd.Timedelta(hours=PAST), hi.max() + pd.Timedelta(
                hours=MAX_K), freq="h")).notna() if len(hi) else None
            if len(hi):
                c = np.concatenate([[0], np.cumsum(have.to_numpy())])
                j = have.index.get_indexer(hi)
                hi = hi[c[j + MAX_K + 1] - c[j - PAST + 1] == PAST + MAX_K]
            if len(hi):
                d = pd.concat([build(q, tw, g, hi, sig=sig, wx_fc=0.0), d], ignore_index=True)
        d["station"] = st
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["station"] = pd.Categorical(d["station"], categories=stations)
    return d
