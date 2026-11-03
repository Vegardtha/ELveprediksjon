"""Features for direkte multi-horisont-prediksjon.

Utstedelsesdag t = siste dag med observert døgnvannføring (i går). For horisont h brukes
observasjoner til og med t og vær/HBV-verdier for t+1..t+h (prognose i drift,
arkivverdier i trening). h=1 er i dag.

Nowcast: i tillegg brukes timesmålinger fra i dag fram til klokkeslett `hour` (UTC).
I trening lages én rad per (dag, time) for HOURS, slik at modellen fungerer uansett
når på døgnet den kjøres.

Vær framover (`weather`):
- "gts": GTS-nedbør/temp/snø og NVEs HBV-prognose. Kan ikke etterprøves på ekte prognoser.
- "wx_perfect": bare nedbør og temperatur, fasit fra GTS-arkivet.
- "wx_fc": bare nedbør og temperatur, fra arkiverte værprognoser (Open-Meteo, fra mars 2024).
- "wx_mixed": som wx_fc der arkivet finnes, ellers fasit – for trening på lang historikk.
"""
import numpy as np
import pandas as pd

from elvepred import upstream
from elvepred.settings import DATA

HORIZONS = list(range(1, 10))
HOURS = (3, 9, 15, 21)


def load_hourly(station: str) -> pd.Series:
    return pd.read_parquet(DATA / "raw" / "hydapi_hourly" / f"{station}.parquet")["q"].dropna()


def load_station(station: str) -> pd.DataFrame:
    q = pd.read_parquet(DATA / "raw" / "hydapi" / f"{station}.parquet")[["q"]]
    w = pd.read_parquet(DATA / "raw" / "gts" / f"{station}.parquet")
    df = w.join(q, how="left")
    return df.asfreq("D")


def _past(df: pd.DataFrame) -> pd.DataFrame:
    lq = np.log1p(df["q"])
    f = pd.DataFrame(index=df.index)
    f["lq0"] = lq
    for k in (1, 2, 3, 7):
        f[f"dlq{k}"] = lq - lq.shift(k)
    f["lq_mean7"] = lq.rolling(7, min_periods=5).mean()
    f["lq_mean30"] = lq.rolling(30, min_periods=20).mean()
    f["lq_min30"] = lq.rolling(30, min_periods=20).min()
    f["lq_max7"] = lq.rolling(7, min_periods=5).max()
    # hvor langt under siste topp og hvor lenge siden: skiller tidlig og sen resesjon
    f["dlq_max7"] = lq - f["lq_max7"]
    f["days_since_max"] = lq.rolling(7, min_periods=5).apply(lambda x: len(x) - 1 - np.argmax(x), raw=True)
    f["rr0"] = df["rr"]
    for k in (3, 7, 14, 30):
        f[f"rr_sum{k}"] = df["rr"].rolling(k, min_periods=1).sum()
    f["tm0"] = df["tm"]
    f["tm_mean3"] = df["tm"].rolling(3, min_periods=1).mean()
    f["tm_mean7"] = df["tm"].rolling(7, min_periods=1).mean()
    f["swe0"] = df["swe"]
    f["dswe7"] = df["swe"] - df["swe"].shift(7)
    f["qtt_sum3"] = df["qtt"].rolling(3, min_periods=1).sum()
    f["qtt_sum7"] = df["qtt"].rolling(7, min_periods=1).sum()
    f["hbv0"] = df["gwb_q"]
    f["hbv_sum7"] = df["gwb_q"].rolling(7, min_periods=1).sum()
    f["lhbv0"] = np.log1p(df["gwb_q"])
    f["dlhbv3"] = f["lhbv0"] - f["lhbv0"].shift(3)
    f["soil0"] = df["gwb_sssrel"]
    f["gw0"] = df["gwb_gwt"]
    doy = df.index.dayofyear
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    return f


def _future(df: pd.DataFrame, h: int) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    for k in range(1, h + 1):
        f[f"rr_f{k}"] = df["rr"].shift(-k)
    fut = lambda col: pd.concat([df[col].shift(-k) for k in range(1, h + 1)], axis=1)
    f["rr_fsum"] = fut("rr").sum(axis=1, min_count=h)
    f["qtt_fsum"] = fut("qtt").sum(axis=1, min_count=h)
    f["tm_fmean"] = fut("tm").mean(axis=1)
    f["dswe_f"] = df["swe"].shift(-h) - df["swe"]
    f["hbv_fh"] = df["gwb_q"].shift(-h)
    f["hbv_fsum"] = fut("gwb_q").sum(axis=1, min_count=h)
    f["dlhbv_f"] = np.log1p(df["gwb_q"].shift(-h)) - np.log1p(df["gwb_q"])
    return f


def load_forecasts(station: str, model: str) -> pd.DataFrame | None:
    """None hvis arkivet ikke er hentet ennå; wx_mixed bruker da fasit for hele perioden."""
    f = DATA / "raw" / "forecasts" / model / f"{station}.parquet"
    return pd.read_parquet(f) if f.exists() else None


def _future_wx(df: pd.DataFrame, h: int, fc: pd.DataFrame | None, mixed: bool = False) -> pd.DataFrame:
    """Framtidig vær kun fra nedbør og temperatur. fc=None gir fasit (GTS-arkivet).
    k=1 (GTS-døgnet som slutter 06 UTC i dag) er observert når modellen kjører, så det tas alltid fra GTS.

    `wx_fc` er 1 når været framover er en ekte prognose og 0 når det er fasit, så modellen kan lære hvor mye
    den skal stole på været (i drift alltid 1). For h=1 sier den bare om raden er fra prognoseperioden."""
    rr, tm = {}, {}
    from_fc = pd.Series(0.0 if fc is None else 1.0, index=df.index)
    if fc is not None and mixed:
        from_fc = fc["rr_fc2"].reindex(df.index).notna().astype(float)
    for k in range(1, h + 1):
        rr[k], tm[k] = df["rr"].shift(-k), df["tm"].shift(-k)
        if fc is not None and k >= 2:
            frr, ftm = fc[f"rr_fc{k}"].reindex(df.index), fc[f"tm_fc{k}"].reindex(df.index)
            if mixed:
                has = frr.notna() & ftm.notna()
                frr, ftm = frr.where(has, rr[k]), ftm.where(has, tm[k])
                from_fc = from_fc.where(has, 0.0)
            rr[k], tm[k] = frr, ftm
    f = pd.DataFrame(index=df.index)
    f["wx_fc"] = from_fc
    for k in range(1, h + 1):
        f[f"rr_f{k}"] = rr[k]
    R, T = pd.concat(rr.values(), axis=1), pd.concat(tm.values(), axis=1)
    f["rr_fsum"] = R.sum(axis=1, min_count=h)
    f["rr_fmax"] = R.max(axis=1)
    f["tm_fmean"] = T.mean(axis=1)
    f["tm_f1"] = tm[1]
    f["pdd_fsum"] = T.clip(lower=0).sum(axis=1, min_count=h)  # graddager → snøsmelting
    f["rain_fsum"] = R.where(T.values > 0.5, 0).sum(axis=1, min_count=h)
    return f


def _nowcast(hq: pd.Series, index: pd.DatetimeIndex, hour: int) -> pd.DataFrame:
    """Dagens timesmålinger for t+1 fram til `hour` UTC."""
    lq = np.log1p(hq)
    sofar = lq.rolling(f"{hour + 1}h").mean()
    now = index + pd.Timedelta(days=1, hours=hour)
    at = lambda s, ts: s.reindex(ts, method="ffill", tolerance=pd.Timedelta("3h")).values
    f = pd.DataFrame(index=index)
    f["lq_now"] = at(lq, now)
    for k in (3, 6, 12, 24):
        f[f"dlq_now{k}h"] = f["lq_now"] - at(lq, now - pd.Timedelta(hours=k))
    f["lq_sofar"] = at(sofar, now)
    f["hour"] = hour
    return f


def load_upstream(station: str) -> tuple[pd.Series, pd.Series, float] | None:
    """(døgn- og timesvannføring, andel av feltet) for nærmeste stasjon oppstrøms, eller None."""
    p = upstream.pairs().get(station)
    if p is None or not (DATA / "raw" / "hydapi" / f"{p[0]}.parquet").exists():
        return None
    return pd.read_parquet(DATA / "raw" / "hydapi" / f"{p[0]}.parquet")["q"], load_hourly(p[0]), p[1]


def _upstream(up: tuple[pd.Series, pd.Series, float], index: pd.DatetimeIndex, lq0: pd.Series,
              hour: int | None) -> pd.DataFrame:
    """Vannføring ved stasjonen oppstrøms. Et slipp fra magasin eller en flombølge der viser seg her
    før den når stasjonen nedstrøms, og andelen av vannet som kommer ovenfra sier hvor mye det betyr."""
    q, hq, share = up
    lu = np.log1p(q.reindex(index))
    f = pd.DataFrame(index=index)
    f["up_share"] = share
    f["up_rel0"] = lu - lq0
    f["up_rel_anom"] = f["up_rel0"] - f["up_rel0"].rolling(30, min_periods=20).mean()
    for k in (1, 3):
        f[f"up_dlq{k}"] = lu - lu.shift(k)
    if hour is not None:
        lh = np.log1p(hq)
        now = index + pd.Timedelta(days=1, hours=hour)
        at = lambda ts: lh.reindex(ts, method="ffill", tolerance=pd.Timedelta("3h")).values
        f["up_dlq_now"] = at(now) - lu
        f["up_dlq_now6h"] = at(now) - at(now - pd.Timedelta(hours=6))
    return f


def build(df: pd.DataFrame, h: int, weather: str | None = "gts", hq: pd.Series | None = None,
          hour: int | None = None, fc: pd.DataFrame | None = None,
          up: tuple[pd.Series, pd.Series, float] | None = None) -> pd.DataFrame:
    """Featurematrise for horisont h med mål `y` = log1p(q[t+h]) - log1p(q[t]).

    up: (døgn- og timesvannføring, feltandel) for stasjonen oppstrøms (`load_upstream`); uten den mangler
    `up_*`-kolonnene, og modellen behandler dem som manglende verdier."""
    parts = [_past(df)]
    if weather == "gts":
        parts.append(_future(df, h))
    elif weather == "wx_perfect":
        parts.append(_future_wx(df, h, None))
    elif weather in ("wx_fc", "wx_mixed"):
        parts.append(_future_wx(df, h, fc, mixed=weather == "wx_mixed"))
    if hq is not None:
        parts.append(_nowcast(hq, df.index, hour))
    if up is not None:
        parts.append(_upstream(up, df.index, parts[0]["lq0"], hour if hq is not None else None))
    X = pd.concat(parts, axis=1)
    if hq is not None:
        X["dlq_now"] = X["lq_now"] - X["lq0"]
    X["y"] = np.log1p(df["q"].shift(-h)) - X["lq0"]
    return X


def signature(df: pd.DataFrame, until: str | None = None) -> dict[str, float]:
    """Faste egenskaper ved feltet, beregnet fra stasjonens egen historikk (til og med `until`).

    Gir modellen et mål på hvor fort akkurat denne elva faller og svinger, så raske felt med kort historikk
    (f.eks. Lysakerelva fra 2020) ikke arver resesjonen til trege, innsjørike felt.
    """
    d = df.loc[:until] if until else df
    lq = np.log1p(d["q"])
    d1 = lq.diff()
    dry = (d["rr"].rolling(3, min_periods=1).sum() < 3) & (d1 < 0)
    high = lq > lq.quantile(0.9)
    q = d["q"].dropna()
    # Resesjonskurve -dq/dt = a·q^b (Brutsaert–Nieber), tilpasset medianer i 10 nivåbånd på tørre dager
    dq = d["q"].diff()
    ok = dry & (dq < 0) & (d["q"] > 0)
    x, yv = np.log(((d["q"] + d["q"].shift()) / 2)[ok]), np.log(-dq[ok])
    bins = pd.qcut(x, 10, duplicates="drop")
    xb, yb = x.groupby(bins, observed=True).median(), yv.groupby(bins, observed=True).median()
    b = float(np.clip(np.polyfit(xb, yb, 1)[0], 0.5, 3.0))
    loga = float(np.median(yb - b * xb))  # konsistent med avklippet b
    return {
        "sig_rec": float(d1[dry].median()),  # typisk døgnlig fall i log-vannføring når det er tørt
        "sig_rec_hi": float(d1[dry & high].median()),  # samme etter flomtopper
        "sig_flash": float(q.diff().abs().sum() / q.sum()),  # Richards-Baker-indeks
        "sig_lq_range": float(lq.quantile(0.95) - lq.quantile(0.05)),
        "sig_rec_loga": float(loga),
        "sig_rec_b": b,
        "sig_q01": float(q.quantile(0.01)),
    }


def recession(q0: np.ndarray, h: float, sig: dict) -> np.ndarray:
    """Endring i log1p-vannføring etter h døgn uten nedbør, fra stasjonens resesjonskurve."""
    a, b = np.exp(sig["sig_rec_loga"]), sig["sig_rec_b"]
    q0 = np.maximum(np.asarray(q0, dtype=float), 1e-6)
    if abs(b - 1) < 0.02:
        qh = q0 * np.exp(-a * h)
    else:
        base = q0 ** (1 - b) - (1 - b) * a * h
        qh = np.where(base > 0, np.abs(base) ** (1 / (1 - b)), 0.0)
    qh = np.clip(qh, min(sig["sig_q01"], q0.min()), q0)
    return np.log1p(qh) - np.log1p(q0)


def add_signature(X: pd.DataFrame, sig: dict, h: int) -> None:
    """Feltsignatur som faste kolonner, pluss `rec_h`: forventet fall de neste h døgnene hvis det er tørt."""
    for k, v in sig.items():
        X[k] = v
    X["rec_h"] = recession(np.expm1(X["lq0"].to_numpy()), h, sig)
    if "lq_now" in X:  # samme fra siste timesmåling, som ligger 1 døgn + `hour` timer etter t
        rest = np.clip(h - 1 - X["hour"].to_numpy() / 24, 0, None)
        X["rec_h_now"] = recession(np.expm1(X["lq_now"].fillna(X["lq0"]).to_numpy()), rest, sig) + X["dlq_now"].fillna(0)


def dataset(stations: list[str], h: int, weather: str | None = "gts", nowcast: bool = True,
            fc_model: str = "ecmwf_ifs025", sig_until: str | bool | None = None,
            upstream: bool = False) -> pd.DataFrame:
    """Treningsdata for alle stasjoner. Kolonner utenom features: date, y, q0, q_true.

    sig_until: legg til feltsignaturer (`signature`) beregnet til og med denne datoen, eller fra all historikk
    hvis True. upstream: legg til vannføring ved stasjonen oppstrøms (`up_*`)."""
    parts = []
    for st in stations:
        df = load_station(st)
        sig = signature(df, None if sig_until is True else sig_until) if sig_until else {}
        hq = load_hourly(st) if nowcast else None
        up = load_upstream(st) if upstream else None
        fc = load_forecasts(st, fc_model) if weather in ("wx_fc", "wx_mixed") else None
        if weather == "wx_fc" and fc is None:  # ingen ekte prognoser: radene skal falle ut av testen, ikke få fasit
            fc = pd.DataFrame(columns=[f"{v}_fc{k}" for v in ("rr", "tm") for k in HORIZONS], dtype=float)
        for hour in (HOURS if nowcast else (None,)):
            X = build(df, h, weather, hq, hour, fc, up)
            X["station"] = st
            if sig:
                add_signature(X, sig, h)
            X["q0"] = df["q"]
            X["q_true"] = df["q"].shift(-h)
            parts.append(X.dropna(subset=["y", "lq0", "dlq1"]))
    d = pd.concat(parts)
    d["station"] = d["station"].astype(pd.CategoricalDtype(stations))
    d.index.name = "date"
    return d.reset_index()


NON_FEATURES = ("date", "y", "q0", "q_true")
