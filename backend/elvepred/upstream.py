"""Målestasjoner oppstrøms, funnet fra nedbørfeltene i catchments.geojson.

B ligger oppstrøms A når B er i samme vassdrag (første ledd i stasjonsnummeret), har mindre felt, og minst
halvparten av hjørnene i B-polygonet ligger inne i A. Polygonene er forenklet, så felles kanter treffer ikke
alltid; 0.5 skiller likevel godt mellom felt inni og naboer. Vi bruker stasjonen med størst felt, som er
nærmest og forklarer mest av vannet (og slipp fra magasiner over den).
"""
import json
from functools import lru_cache

from elvepred.clients.gts import _inside
from elvepred.settings import CONFIG

MIN_INSIDE = 0.5


def _rings(f: dict) -> list[list[tuple]]:
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return [[tuple(c) for c in p[0]] for p in polys]


@lru_cache
def pairs() -> dict[str, tuple[str, float]]:
    """{stasjon: (nærmeste stasjon oppstrøms, andel av feltarealet)}."""
    gj = json.loads((CONFIG / "catchments.geojson").read_text(encoding="utf-8"))
    F = {f["properties"]["stasjonnr"]: f for f in gj["features"]}
    area = {s: f["properties"]["nedborfeltaareal_km2"] for s, f in F.items()}
    rings = {s: _rings(f) for s, f in F.items()}
    out = {}
    for a in F:
        best = None
        for b in F:
            if b == a or b.split(".")[0] != a.split(".")[0] or area[b] >= area[a]:
                continue
            v = [p for r in rings[b] for p in r]
            inside = sum(any(_inside(x, y, r) for r in rings[a]) for x, y in v) / len(v)
            if inside > MIN_INSIDE and (best is None or area[b] > area[best]):
                best = b
        if best:
            out[a] = (best, area[best] / area[a])
    return out
