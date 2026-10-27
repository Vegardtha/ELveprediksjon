"""Henter seksjonsmetadata fra nokken.net (CC BY-NC-SA 4.0): elv, region, grad, NVE-stasjon, optimalt intervall.

Høflig: ett kall per sekund. Skrives til data/reference/nokken_sections.json.
"""
import html
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from elvepred.settings import DATA

BASE = "https://nokken.net"
client = httpx.Client(headers={"User-Agent": "elvepred/0.1 (privat, ikke-kommersielt)"}, timeout=60)


def get(path: str) -> str:
    time.sleep(1.0)
    r = client.get(BASE + path)
    r.raise_for_status()
    return r.text


def text(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


rivers_html = get("/rivers")
rivers = {}
for m in re.finditer(r'<a class="rrow" href="/river/(\d+)">(.*?)</a>', rivers_html, re.S):
    region = re.search(r'class="rrow-region">([^<]+)<', m.group(2))
    rivers.setdefault(m.group(1), region.group(1).strip() if region else None)

sections = []
for rid, region in rivers.items():
    rh = get(f"/river/{rid}")
    river_name = text(re.search(r"<h1[^>]*>(.*?)</h1>", rh, re.S).group(1)) if re.search(r"<h1", rh) else None
    for sid in dict.fromkeys(re.findall(r'href="/section/(\d+)"', rh)):
        sh = get(f"/section/{sid}")
        t = text(sh)
        name = text(re.search(r"<h1[^>]*>(.*?)</h1>", sh, re.S).group(1)) if re.search(r"<h1", sh) else None
        station = re.search(r"station (\d+\.\d+\.\d+)", t)
        grade = re.search(r"grade ([IVX]+[+\-−]?(?: ?\([^)]*\))?)", t)
        band = re.search(r"optimal flow ([\d.,]+) – ([\d.,]+) (m³/s|cm|m)", t)
        bands = re.search(r'\{"bands": (\[.*?\])', html.unescape(sh))
        feats = {f["type_slug"]: f for f in map(json.loads, re.findall(r'\{"feature_id"[^}]*\}', html.unescape(sh)))}
        sections.append({
            "river_id": rid, "river": river_name, "region": region, "section_id": sid, "section": name,
            "station": station.group(1) if station else None, "grade": grade.group(1) if grade else None,
            "opt_min": float(band.group(1).replace(",", ".")) if band else None,
            "opt_max": float(band.group(2).replace(",", ".")) if band else None,
            "unit": band.group(3) if band else None,
            "bands": json.loads(bands.group(1)) if bands else None,
            "putin": [feats["putin"]["lat"], feats["putin"]["lng"]] if "putin" in feats else None,
            "takeout": [feats["takeout"]["lat"], feats["takeout"]["lng"]] if "takeout" in feats else None,
        })
    print(f"{rid:>4} {region or '-':11s} {river_name}", flush=True)

out = DATA / "reference"
out.mkdir(parents=True, exist_ok=True)
(out / "nokken_sections.json").write_text(json.dumps(sections, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(rivers), "elver,", len(sections), "seksjoner")
