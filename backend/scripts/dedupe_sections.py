"""Fjerner nokken-seksjoner som ligger oppå en whitewater.guide-seksjon, eller som mangler innsett og gjelder
samme elv som en whitewater.guide-seksjon på samme målestasjon.

whitewater.guide er grunnlaget: der en nokken-seksjon og en whitewater.guide-seksjon dekker samme strekning, eller
den ene ligger inni den andre, beholdes bare whitewater.guide-seksjonen. Overlapp måles på elvelinjene fra
fetch_section_lines.py: andelen av den ene linjen som ligger nærmere enn 80 m den andre. Over 50 % i én av
retningene regnes som overlapp.

Kjør etter add_sections.py og fetch_section_lines.py. `--dry-run` viser bare hva som ville blitt fjernet.
"""
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elvepred.settings import CONFIG, load_rivers

NEAR_M = 80
MIN_OVERLAP = 0.5


def dist(a, b) -> float:
    """Omtrentlig avstand i meter mellom (lat, lon)-punkter (nøyaktig nok på korte avstander)."""
    return 6371000 * math.hypot(math.radians(b[0] - a[0]), math.radians(b[1] - a[1]) * math.cos(math.radians(a[0])))


def dense(line: list) -> list:
    """Punkter for hver ~25 m langs linjen."""
    out = []
    for a, b in zip(line, line[1:]):
        n = max(1, int(dist(a, b) // 25))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    return out + [line[-1]]


def cover(a: list, b: list) -> float:
    """Andelen av a som ligger nær b."""
    return sum(1 for p in a if any(dist(p, q) < NEAR_M for q in b)) / len(a)


fc = json.loads((CONFIG / "section_lines.geojson").read_text(encoding="utf-8"))
lines = {f["properties"]["id"]: dense([(c[1], c[0]) for c in f["geometry"]["coordinates"]]) for f in fc["features"]}
rivers = [r for r in load_rivers() if r["id"] in lines]
ww = [r for r in rivers if r.get("wwguide_section")]
drop = {}
for r in (r for r in rivers if not r.get("wwguide_section")):
    a = lines[r["id"]]
    for w in ww:
        b = lines[w["id"]]
        if dist(a[0], b[0]) > 40000:
            continue
        ca, cb = cover(a, b), cover(b, a)
        if max(ca, cb) > MIN_OVERLAP:
            drop[r["id"]] = w["id"]
            print(f"{r['id']:32s} → {w['id']:36s} ({ca:.0%} / {cb:.0%})")
            break

# nokken-seksjoner uten innsett (bare elvenavn) i samme elv som en whitewater.guide-seksjon på samme stasjon
river = lambda r: r["name"].split(" – ")[0]
for r in load_rivers():
    w = next((w for w in ww if not r.get("putin") and w["station"] == r["station"] and river(w) == river(r)), None)
    if w and not r.get("wwguide_section"):
        drop[r["id"]] = w["id"]
        print(f"{r['id']:32s} → {w['id']:36s} (uten innsett, samme elv)")

left = {r["station"] for r in load_rivers() if r["id"] not in drop}
lost = {r["station"] for r in load_rivers()} - left
if lost:
    print("stasjoner uten seksjoner etterpå:", ", ".join(sorted(lost)))
print(len(drop), "seksjoner fjernes")

if drop and "--dry-run" not in sys.argv:
    f = CONFIG / "rivers.yaml"
    text = f.read_text(encoding="utf-8")
    head, *blocks = re.split(r"(?m)^(?=- id: )", text)
    keep = [b for b in blocks if b.split("\n", 1)[0][len("- id: "):].strip() not in drop]
    f.write_text(head + "".join(keep), encoding="utf-8")
    fc["features"] = [x for x in fc["features"] if x["properties"]["id"] not in drop]
    (CONFIG / "section_lines.geojson").write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
