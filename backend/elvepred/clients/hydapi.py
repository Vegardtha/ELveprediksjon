"""NVE HydAPI – observert vannføring."""

import pandas as pd

from elvepred.clients import http
from elvepred.settings import NVE_API_KEY

BASE = "https://hydapi.nve.no/api/v1"
DISCHARGE = 1001


def _get(path: str, params: dict) -> dict:
    return http.get(f"{BASE}/{path}", attempts=6, params=params, headers={"X-API-Key": NVE_API_KEY},
                    timeout=180).json()


def daily_discharge(station: str, start: str, end: str) -> pd.DataFrame:
    """Døgnmiddel vannføring (m³/s). Indeks: dato."""
    j = _get("Observations", {
        "StationId": station, "Parameter": DISCHARGE, "ResolutionTime": 1440,
        "ReferenceTime": f"{start}/{end}",
    })
    obs = j["data"][0]["observations"] if j["data"] else []
    df = pd.DataFrame(obs)
    if df.empty:
        return pd.DataFrame(columns=["q", "quality"])
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    return df.set_index("date").rename(columns={"value": "q"})[["q", "quality"]]


def latest_discharge(stations: list[str]) -> pd.DataFrame:
    """Siste momentanverdi per stasjon (gorge-mønster: siste 3 timer, batch)."""
    j = _get("Observations", {
        "StationId": ",".join(stations), "Parameter": DISCHARGE, "ResolutionTime": 0,
        "ReferenceTime": "PT3H/",
    })
    rows = []
    for d in j["data"]:
        if d["observations"]:
            o = d["observations"][-1]
            rows.append({"station": d["stationId"], "time": o["time"], "q": o["value"]})
    return pd.DataFrame(rows)


def hourly_discharge(station: str, start: str, end: str) -> pd.Series:
    """Timesverdier vannføring (m³/s), UTC-indeks uten tidssone. Hentes år for år."""
    parts, s, end_ts = [], pd.Timestamp(start), pd.Timestamp(end)
    while s <= end_ts:
        e = min(s + pd.DateOffset(years=1), end_ts + pd.Timedelta(days=1))
        j = _get("Observations", {
            "StationId": station, "Parameter": DISCHARGE, "ResolutionTime": 60,
            "ReferenceTime": f"{s:%Y-%m-%dT%H:%M:%S}/{e:%Y-%m-%dT%H:%M:%S}",
        })
        obs = j["data"][0]["observations"] if j["data"] else []
        if obs:
            df = pd.DataFrame(obs)
            parts.append(pd.Series(df["value"].astype(float).values,
                                   index=pd.to_datetime(df["time"]).dt.tz_localize(None), name="q"))
        s = e
    if not parts:
        return pd.Series(dtype=float, name="q")
    q = pd.concat(parts)
    return q[~q.index.duplicated()].sort_index()
