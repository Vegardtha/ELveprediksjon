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


def load_forecasts(station: str, model: str) -> pd.DataFrame:
    return pd.read_parquet(DATA / "raw" / "forecasts" / model / f"{station}.parquet")


def _future_wx(df: pd.DataFrame, h: int, fc: pd.DataFrame | None, mixed: bool = False) -> pd.DataFrame:
    """Framtidig vær kun fra nedbør og temperatur. fc=None gir fasit (GTS-arkivet).
    k=1 (GTS-døgnet som slutter 06 UTC i dag) er observert når modellen kjører, så det tas alltid fra GTS."""
    rr, tm = {}, {}
    for k in range(1, h + 1):
        rr[k], tm[k] = df["rr"].shift(-k), df["tm"].shift(-k)
        if fc is not None and k >= 2:
            frr, ftm = fc[f"rr_fc{k}"].reindex(df.index), fc[f"tm_fc{k}"].reindex(df.index)
            if mixed:
                has = frr.notna() & ftm.notna()
                frr, ftm = frr.where(has, rr[k]), ftm.where(has, tm[k])
            rr[k], tm[k] = frr, ftm
    f = pd.DataFrame(index=df.index)
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


def build(df: pd.DataFrame, h: int, weather: str | None = "gts", hq: pd.Series | None = None,
          hour: int | None = None, fc: pd.DataFrame | None = None) -> pd.DataFrame:
    """Featurematrise for horisont h med mål `y` = log1p(q[t+h]) - log1p(q[t])."""
    parts = [_past(df)]
    if weather == "gts":
        parts.append(_future(df, h))
    elif weather == "wx_perfect":
        parts.append(_future_wx(df, h, None))
    elif weather in ("wx_fc", "wx_mixed"):
        parts.append(_future_wx(df, h, fc, mixed=weather == "wx_mixed"))
    if hq is not None:
        parts.append(_nowcast(hq, df.index, hour))
    X = pd.concat(parts, axis=1)
    if hq is not None:
        X["dlq_now"] = X["lq_now"] - X["lq0"]
    X["y"] = np.log1p(df["q"].shift(-h)) - X["lq0"]
    return X


def dataset(stations: list[str], h: int, weather: str | None = "gts", nowcast: bool = True,
            fc_model: str = "ecmwf_ifs025") -> pd.DataFrame:
    """Treningsdata for alle stasjoner. Kolonner utenom features: date, y, q0, q_true."""
    parts = []
    for st in stations:
        df = load_station(st)
        hq = load_hourly(st) if nowcast else None
        fc = load_forecasts(st, fc_model) if weather in ("wx_fc", "wx_mixed") else None
        for hour in (HOURS if nowcast else (None,)):
            X = build(df, h, weather, hq, hour, fc)
            X["station"] = st
            X["q0"] = df["q"]
            X["q_true"] = df["q"].shift(-h)
            parts.append(X.dropna(subset=["y", "lq0", "dlq1"]))
    d = pd.concat(parts)
    d["station"] = d["station"].astype(pd.CategoricalDtype(stations))
    d.index.name = "date"
    return d.reset_index()


NON_FEATURES = ("date", "y", "q0", "q_true")
