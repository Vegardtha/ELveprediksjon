"""NVE GridTimeSeries (seNorge 1 km) – feltmiddel av vær, snø og HBV-avrenning.

Arkivet inneholder observasjonsbaserte verdier fram til i dag og MET-prognose ~9 dager fram.
`AggregationTimeSeries/ByGeoJson` ignorerer geometrien (gir samme svar for alle felt), så
feltmiddelet beregnes selv fra punktserier på et rutenett av celler inne i nedbørfeltet.
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import httpx
import pandas as pd

from elvepred.settings import CONFIG

URL = "https://gts.nve.no/api/GridTimeSeries/{x}/{y}/{start}/{end}/{theme}.json"
NODATA = 65535
# rr nedbør mm, tm temp °C, swe snømengde mm, qtt regn+snøsmelting mm,
# gwb_q HBV-avrenning mm, gwb_sssrel vannmetning i jord %, gwb_gwt grunnvann mm
THEMES = ["rr", "tm", "swe", "qtt", "gwb_q", "gwb_sssrel", "gwb_gwt"]
POINTS_PER_CATCHMENT = 16

_client = httpx.Client(timeout=180)


def _inside(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


@lru_cache
def sample_points(station: str, n: int = POINTS_PER_CATCHMENT) -> list[tuple[int, int]]:
    """Rutenett av 1 km-cellesentre (UTM33) inne i nedbørfeltet, ca. n punkter."""
    gj = json.loads((CONFIG / "catchments.geojson").read_text(encoding="utf-8"))
    f = next(x for x in gj["features"] if x["properties"]["stasjonnr"] == station)
    geom = f["geometry"]
    rings = [geom["coordinates"][0]] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
    area_km2 = f["properties"]["nedborfeltaareal_km2"]
    step = max(1000, int(math.sqrt(area_km2 / n) * 1000) // 1000 * 1000)
    xs = [c[0] for r in rings for c in r]
    ys = [c[1] for r in rings for c in r]
    pts = []
    for x in range(int(min(xs)) // 1000 * 1000 + 500, int(max(xs)) + 1, step):
        for y in range(int(min(ys)) // 1000 * 1000 + 500, int(max(ys)) + 1, step):
            if any(_inside(x, y, [tuple(c) for c in r]) for r in rings):
                pts.append((x, y))
    return pts


def point_series(x: int, y: int, theme: str, start: str, end: str) -> pd.Series:
    for attempt in range(3):
        try:
            r = _client.get(URL.format(x=x, y=y, start=start, end=end, theme=theme))
            r.raise_for_status()
            break
        except (httpx.HTTPStatusError, httpx.TransportError):
            if attempt == 2:
                raise
    j = r.json()
    # seNorge-døgn stemples 06:00; normaliseres til dato for å matche HydAPI
    idx = pd.date_range(pd.to_datetime(j["StartDate"], dayfirst=True).normalize(), periods=len(j["Data"]), freq="D")
    s = pd.Series(j["Data"], index=idx, dtype=float)
    return s.where(s != NODATA)


def frame(station: str, start: str, end: str, themes=THEMES) -> pd.DataFrame:
    """Feltmiddel per tema. `end` kan ligge inntil ~9 dager fram (prognose)."""
    pts = sample_points(station)
    jobs = [(t, x, y) for t in themes for x, y in pts]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: _point_or_none(j[1], j[2], j[0], start, end), jobs))
    cols = {}
    for t in themes:
        ss = [s for (tt, _, _), s in zip(jobs, res) if tt == t and s is not None]
        if not ss:
            raise ValueError(f"{station}: ingen GTS-punkter for {t}")
        cols[t] = pd.concat(ss, axis=1).mean(axis=1)
    return pd.DataFrame(cols)


def _point_or_none(x: int, y: int, theme: str, start: str, end: str) -> pd.Series | None:
    """Punkter utenfor seNorge-rutenettet (felt som går inn i Sverige) gir HTTP 400 og utelates."""
    try:
        return point_series(x, y, theme, start, end)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return None
        raise


def last_available(station: str, today: pd.Timestamp, max_days: int = 12) -> pd.Timestamp:
    """Siste dag GTS har prognose for (forespørsel forbi slutten gir HTTP 500)."""
    x, y = sample_points(station)[0]
    lo, hi = 0, max_days
    while lo < hi:
        mid = (lo + hi + 1) // 2
        try:
            point_series(x, y, "rr", today.strftime("%Y-%m-%d"), (today + pd.Timedelta(days=mid)).strftime("%Y-%m-%d"))
            lo = mid
        except httpx.HTTPStatusError:
            hi = mid - 1
    return today + pd.Timedelta(days=lo)
