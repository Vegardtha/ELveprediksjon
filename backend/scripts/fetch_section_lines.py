"""Tegner hver seksjon langs elva: korteste vei i NVEs elvenett (ELVIS) fra innsett til utsett.

Henter elvenettet rundt innsett og utsett fra NVEs kartjeneste, kobler linjene til en graf og finner korteste vei
mellom nærmeste punkt på elva ved innsett og utsett. Elvenettet har midtlinjer gjennom innsjøer, så det henger
sammen. Små bekker (lav Strahler-orden) vektes tyngre, så veien følger hovedelva. Seksjoner der innsett/utsett
ligger langt fra elvenettet, eller veien blir urimelig lang, får ingen linje (kartet viser da en rett strek).
Rådata caches i data/cache/elvenett.

Skriver config/section_lines.geojson (NVE, NLOD 2.0). Kjør på nytt etter add_sections.py;
`--force` beregner alt på nytt, ellers bare seksjoner som mangler.
"""
import heapq
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from elvepred.settings import CONFIG, DATA, load_rivers

URL = "https://kart.nve.no/enterprise/rest/services/Elvenett1/FeatureServer/2/query"
CACHE = DATA / "cache" / "elvenett"
OUT = CONFIG / "section_lines.geojson"
MAX_SNAP_M = 800
MAX_GAP_M = 300  # små hull i nettet (f.eks. ved riksgrensen eller kraftverk) bygges det bro over
MIN_STEP_M = 30  # tynner ut punktene så filen holder seg liten


def dist(a, b) -> float:
    """Avstand i meter mellom (lat, lon)-punkter."""
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def elvenett(rid: str, putin, takeout) -> list[dict]:
    f = CACHE / f"{rid}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    pad = max(0.012, 0.15 * max(abs(putin[0] - takeout[0]), abs(putin[1] - takeout[1])))
    s, n = min(putin[0], takeout[0]) - pad, max(putin[0], takeout[0]) + pad
    w, e = min(putin[1], takeout[1]) - 1.8 * pad, max(putin[1], takeout[1]) + 1.8 * pad
    out, offset = [], 0
    while True:
        r = httpx.get(URL, timeout=120, headers={"User-Agent": "elvepred/0.1"}, params={
            "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "elveordenstrahler", "outSR": 4326,
            "resultOffset": offset, "f": "geojson"})
        r.raise_for_status()
        j = r.json()
        out += [{"order": x["properties"].get("elveordenstrahler") or 1, "coords": x["geometry"]["coordinates"]}
                for x in j["features"] if x.get("geometry")]
        if not j.get("exceededTransferLimit") and not j.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(j["features"])
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out), encoding="utf-8")
    return out


def route(lines: list[dict], putin, takeout) -> list | None:
    key = lambda c: (round(c[1], 6), round(c[0], 6))  # (lat, lon); linjene møtes i identiske endepunkter
    graph = {}
    for ln in lines:
        k = {1: 3.0, 2: 2.0}.get(ln["order"], 1.0)
        pts = [key(c) for c in ln["coords"]]
        for a, b in zip(pts, pts[1:]):
            d = dist(a, b) * k
            graph.setdefault(a, []).append((b, d))
            graph.setdefault(b, []).append((a, d))
    if not graph:
        return None
    ends = [i for i, e in graph.items() if len(e) == 1]
    for n, a in enumerate(ends):
        for b in ends[n + 1:]:
            d = dist(a, b)
            if d < MAX_GAP_M:
                graph[a].append((b, 1.5 * d))
                graph[b].append((a, 1.5 * d))
    start = min(graph, key=lambda i: dist(i, putin))
    end = min(graph, key=lambda i: dist(i, takeout))
    if dist(start, putin) > MAX_SNAP_M or dist(end, takeout) > MAX_SNAP_M or start == end:
        return None
    best, prev, todo = {start: 0.0}, {}, [(0.0, start)]
    while todo:
        d, i = heapq.heappop(todo)
        if i == end:
            break
        if d > best[i]:
            continue
        for j, w in graph[i]:
            if d + w < best.get(j, math.inf):
                best[j], prev[j] = d + w, i
                heapq.heappush(todo, (d + w, j))
    if end not in prev:
        return None
    pts = [end]
    while pts[-1] != start:
        pts.append(prev[pts[-1]])
    pts.reverse()
    length = sum(dist(a, b) for a, b in zip(pts, pts[1:]))
    if length > 3 * dist(putin, takeout) + 1000:
        return None
    thin = [pts[0]]
    for p in pts[1:-1]:
        if dist(thin[-1], p) >= MIN_STEP_M:
            thin.append(p)
    return [[round(p[1], 5), round(p[0], 5)] for p in thin + [pts[-1]]]


old = {f["properties"]["id"]: f for f in json.loads(OUT.read_text(encoding="utf-8"))["features"]} if OUT.exists() else {}
features, missing = [], []
for r in load_rivers():
    if not (r.get("putin") and r.get("takeout")):
        continue
    if r["id"] in old and "--force" not in sys.argv:
        features.append(old[r["id"]])
        continue
    try:
        line = route(elvenett(r["id"], r["putin"], r["takeout"]), r["putin"], r["takeout"])
    except httpx.HTTPError as e:
        print(f"{r['id']}: elvenettet feilet ({e})")
        line = None
    if line:
        features.append({"type": "Feature", "properties": {"id": r["id"]}, "geometry": {"type": "LineString", "coordinates": line}})
        print(f"{r['id']:40s} {len(line)} punkter")
    else:
        missing.append(r["id"])
        print(f"{r['id']:40s} ingen linje")

OUT.write_text(json.dumps({"type": "FeatureCollection", "attribution": "NVE Elvenett (ELVIS), NLOD 2.0",
                           "features": features}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"{len(features)} linjer, {len(missing)} uten: {', '.join(missing)}")
