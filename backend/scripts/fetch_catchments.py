"""Henter nedbørfelt-polygoner (UTM33) for målestasjonene fra NVE kart.nve.no."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from elvepred.settings import load_rivers

URL = "https://kart.nve.no/enterprise/rest/services/HydrologiskeData3/MapServer/38/query"
STATIONS = sorted({r["station"] for r in load_rivers()})
OUT = Path(__file__).resolve().parents[1] / "config" / "catchments.geojson"

params = {
    "where": "stasjonnr IN (%s)" % ",".join(f"'{s}'" for s in STATIONS),
    "outFields": "stasjonnr,stasjonnavn,nedborfeltaareal_km2",
    "outSR": 25833,
    "maxAllowableOffset": 250,  # forenkler polygonet; GTS avviser store GeoJSON
    "geometryPrecision": 0,
    "f": "geojson",
}
r = httpx.get(URL, params=params, timeout=120)
r.raise_for_status()
gj = r.json()
OUT.write_text(json.dumps(gj), encoding="utf-8")
for f in gj["features"]:
    p = f["properties"]
    print(p["stasjonnr"], p["stasjonnavn"], p["nedborfeltaareal_km2"], f["geometry"]["type"])
