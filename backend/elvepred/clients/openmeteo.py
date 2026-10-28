"""Open-Meteo Previous Runs API – arkiverte værprognoser med ledetid 0–7 døgn (fra mars 2024).

`<var>_previous_dayN` for et tidspunkt er verdien fra modellkjøringen N døgn før tidspunktets dato.
Brukes til å trene og evaluere på ekte prognoser i stedet for fasitvær.
"""
import time

import httpx
import pandas as pd
from pyproj import Transformer

from elvepred.clients import gts, http

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_START = "2024-03-01"
LEADS = range(0, 8)
VARS = ("precipitation", "temperature_2m")
# Gratis-API-et har kvote per minutt/time/døgn vektet etter variabler × dager × punkter.
# ECMWF har ~25 km rutenett, så få punkter er nok; MET Nordic (1 km) får noen flere.
N_POINTS = {"ecmwf_ifs025": 3, "metno_seamless": 4}
_utm_to_wgs = Transformer.from_crs(25833, 4326, always_xy=True)


def points(station: str, n: int = 8) -> list[tuple[float, float]]:
    """Inntil n av GTS-punktene i feltet, jevnt fordelt, som (lat, lon)."""
    pts = gts.sample_points(station)
    pick = pts[:: max(1, len(pts) // n)][:n]
    return [tuple(reversed(_utm_to_wgs.transform(x, y))) for x, y in pick]


QUOTA_WAIT_S = 2 * 3600


def hourly(station: str, model: str, start: str, end: str) -> pd.DataFrame:
    """Feltmiddel per time. Kolonner `rr_l{N}` (mm) og `tm_l{N}` (°C) for ledetid N døgn."""
    pts = points(station, N_POINTS.get(model, 4))
    names = {f"{v}{'' if n == 0 else f'_previous_day{n}'}": f"{'rr' if v == 'precipitation' else 'tm'}_l{n}"
             for v in VARS for n in LEADS}
    parts, s = [], pd.Timestamp(start)
    while s <= pd.Timestamp(end):
        e = min(s + pd.DateOffset(months=6) - pd.Timedelta(days=1), pd.Timestamp(end))
        attempt, waited = 0, 0
        while True:
            try:
                r = httpx.get(URL, timeout=300, params={
                    "latitude": ",".join(f"{p[0]:.4f}" for p in pts), "longitude": ",".join(f"{p[1]:.4f}" for p in pts),
                    "hourly": ",".join(names), "models": model, "start_date": f"{s:%Y-%m-%d}", "end_date": f"{e:%Y-%m-%d}",
                })
                # gratiskvoten gjelder per minutt, time og døgn. Døgnkvoten (ca. 5 stasjoner arkiv) nullstilles
                # ved midnatt UTC: da ventes det til neste døgn, så arkivet for mange nye stasjoner hentes over flere dager
                if r.status_code == 429 and "daily" in r.text.lower():
                    reset = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1, minutes=10)
                    print(f"Open-Meteo døgnkvote brukt opp, venter til {reset:%Y-%m-%d %H:%M} UTC", flush=True)
                    while pd.Timestamp.now(tz="UTC") < reset:  # korte søvner: tiden PC-en sover telles ikke av sleep()
                        time.sleep(60)
                    continue
                if r.status_code == 429 and waited < QUOTA_WAIT_S:
                    pause = 65 if "minutely" in r.text.lower() else 300
                    print(f"Open-Meteo 429 ({r.text[:80]}), venter {pause}s", flush=True)
                    time.sleep(pause)
                    waited += pause
                    continue
                r.raise_for_status()
                j = r.json()  # kan feile ved avkuttet svar
                break
            except (httpx.TransportError, ValueError):
                attempt += 1
                if attempt == 30:
                    raise
                time.sleep(60)  # også nettbrudd (f.eks. DNS) som varer noen minutter
        r.raise_for_status()
        js = j if isinstance(j, list) else [j]
        frames = [pd.DataFrame(j["hourly"]).set_index("time").rename(columns=names) for j in js]
        df = pd.concat(frames).groupby(level=0).mean()
        df.index = pd.to_datetime(df.index)
        parts.append(df)
        s = e + pd.Timedelta(days=1)
    return pd.concat(parts)


def daily_forecasts(h: pd.DataFrame, horizons=range(2, 10)) -> pd.DataFrame:
    """Døgnprognoser per utstedelsesdag t (i går), slik features.py forventer.

    GTS/seNorge stempler et døgn på slutten: dato T = 06 UTC T-1 til 06 UTC T. Kolonne
    rr_fc{k}/tm_fc{k} er prognosen for GTS-døgn t+k fra kjøringen i dag (t+1). Timer på dato X
    har da ledetid X-(t+1) døgn: k-2 for timene på T-1, k-1 for timene på T. k=1 (fram til 06 UTC
    i dag) er allerede observert og tas fra GTS. Ledetid over 7 settes til 7 (arkivets grense),
    svakt optimistisk for k=9.
    """
    hour, day = h.index.hour, h.index.normalize()
    late, early = hour >= 6, hour < 6
    out = {}
    for var, agg in (("rr", "sum"), ("tm", "mean")):
        for k in horizons:
            a = h.loc[late, f"{var}_l{min(k - 2, 7)}"]
            b = h.loc[early, f"{var}_l{min(k - 1, 7)}"]
            # begge deler indekseres på GTS-døgnet T: dato+1 for sene timer, samme dato for tidlige
            v = pd.concat([a.set_axis(day[late] + pd.Timedelta(days=1)), b.set_axis(day[early])])
            g = v.groupby(level=0)
            daily = g.agg(agg).where(g.count() >= 20)
            daily.index = daily.index - pd.Timedelta(days=k)  # indekser på utstedelsesdag t
            out[f"{var}_fc{k}"] = daily
    return pd.DataFrame(out).sort_index()


LIVE_URL = "https://api.open-meteo.com/v1/forecast"


def live_hourly(station: str, model: str, past_days: int = 3, forecast_days: int = 10) -> pd.DataFrame:
    """Siste prognose per time med kolonner rr_l{N}/tm_l{N}. Én kjøring, så alle ledetider er like."""
    pts = points(station, N_POINTS.get(model, 4))
    r = http.get(LIVE_URL, timeout=60, params={
        "latitude": ",".join(f"{p[0]:.4f}" for p in pts), "longitude": ",".join(f"{p[1]:.4f}" for p in pts),
        "hourly": "precipitation,temperature_2m", "models": model, "past_days": past_days,
        "forecast_days": forecast_days,
    })
    js = r.json() if isinstance(r.json(), list) else [r.json()]
    df = pd.concat(pd.DataFrame(j["hourly"]).set_index("time") for j in js).groupby(level=0).mean()
    df.index = pd.to_datetime(df.index)
    return pd.DataFrame({f"{v}_l{n}": df[src] for v, src in (("rr", "precipitation"), ("tm", "temperature_2m"))
                         for n in LEADS}, index=df.index)


def live_daily(station: str, model: str) -> pd.DataFrame:
    """Siste prognose i samme format som daily_forecasts (én kjøring, ledetid ut fra dagens dato)."""
    return daily_forecasts(live_hourly(station, model, past_days=2))
