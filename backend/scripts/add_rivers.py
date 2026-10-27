"""Legger til nye elver i config/rivers.yaml fra nokken.net/whitewater.guide-seksjoner og NVE HydAPI-stasjonsdata.

SECTIONS velger én seksjon per målestasjon. Terskler fra nokken (LOW.min → minimum, GOOD → optimum..maximum,
VERY HIGH.min eller HIGH.max → impossible), ellers whitewater.guide. Regulering fra HydAPI Stations.
Elver som allerede finnes (samme stasjon) hoppes over.

Krever data/reference/nokken_sections.json (scripts/fetch_nokken.py) og data/reference/wwguide_sections_raw.json
(svaret på GraphQL-spørringen `sections(filter:{regionId}, page:{limit:1000})` mot https://api.whitewater.guide/graphql
med feltene name, river.name, gauge.code og flows). Deretter: fetch_catchments.py og fetch_*.py --new, og ny trening.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from elvepred.clients import hydapi
from elvepred.settings import CONFIG, DATA, load_rivers

# stasjon → (elv, seksjon) i nokken_sections.json; Frya har bare nivåer på whitewater.guide
SECTIONS = {
    "12.171.0": ("Bøva", "Bøva"),
    "12.209.0": ("Urula", "Urula"),
    "12.215.0": ("Mørkedøla", "Mørkedøla"),
    "12.290.0": ("Begna", "Upper"),
    "12.70.0": ("Etna", "Upper"),
    "15.61.0": ("Numedalslågen", "Vrangfoss play spot"),
    "15.79.0": ("Numedalslågen", "Dagali"),
    "16.128.0": ("Austbygdåi", "Middle"),
    "16.155.0": ("Skogsåa", "Skogsåa"),
    "2.1151.0": ("Frya", "Frya"),
    "2.129.0": ("Folla", "Upper"),
    "2.25.0": ("Otta", "Family run"),
    "2.265.0": ("Unsetåa", "Unsetåa"),
    "2.267.0": ("Mistra", "Mistra"),
    "2.268.0": ("Bøvra", "Lower"),
    "2.275.0": ("Ostri", "Upper"),
    "2.284.0": ("Finna", "Finna"),
    "2.290.0": ("Bøvra", "Upper"),
    "2.291.0": ("Tora", "Tora"),
    "2.303.0": ("Jori", "Lower"),
    "2.32.0": ("Atna", "Lower I"),
    "2.434.0": ("Otta", "Skjåkbølgen (play-spot)"),
    "2.439.0": ("Åsta", "Åsta"),
    "2.479.0": ("Atna", "Dørålen"),
    "2.578.0": ("Imsa", "Upper"),
    "2.595.0": ("Sjoa", "Play-run"),
    "2.614.0": ("Gudbrandsdalslågen", "Rosten"),
    "311.4.0": ("Femundselva", "Middle"),
    "311.460.0": ("Rømoåa", "Rømoåa"),
}
WWGUIDE = {"2.1151.0": ("Frya", "Gorge")}
# målestasjonen står i en annen (nabo)elv enn seksjonen
PROXY = {"12.171.0", "12.215.0", "311.460.0"}


def slug(s: str) -> str:
    s = s.lower().replace("ø", "o").replace("æ", "ae").replace("å", "a")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def nokken_thresholds(bands: list[dict]) -> dict | None:
    b = {x["label"]: x for x in bands}
    if "GOOD" not in b:
        return None
    good = b["GOOD"]
    hi = b.get("VERY HIGH", {}).get("min") or b.get("HIGH", {}).get("max") or good["max"]
    t = {"minimum": b.get("LOW", good)["min"], "optimum": good["min"], "maximum": good["max"], "impossible": hi}
    return {k: round(v, 1) for k, v in t.items()} | {"source": "nokken.net"}


def pct(x: float) -> str:
    return f"{round(100 * x)} %"


def regulation(d: dict) -> tuple[str, str]:
    area, reg = d["drainageBasinArea"], d.get("regulationArea")
    if reg is None:
        return "unknown", "NVE har ikke reguleringsdata for stasjonen."
    frac, part, n = reg / area, d.get("regulationPartReservoirs") or 0, d.get("numberReservoirs") or 0
    transfer = (d.get("transferAreaIn") or 0) + (d.get("transferAreaOut") or 0)
    if frac >= 0.5 and part >= 0.05:
        return "regulated", (f"Magasinregulert: {n} magasiner, {pct(frac)} av feltet regulert, magasinene rommer "
                             f"{pct(part)} av årsavrenningen (NVE). Slipp kan endre vannføringen raskt.")
    if frac > 0.02:
        return "partly", f"Ca. {pct(frac)} av feltet går gjennom regulerte magasiner (NVE). Noe påvirkning."
    if transfer > 0.02 * area:
        return "partly", f"Overføringer berører ca. {round(transfer)} km² av feltet (NVE). Noe påvirkning."
    if n > 0 or (d.get("firstYearRegulation") or 0) > 0:
        return "partly", "NVE registrerer magasiner eller regulering i feltet, men uten regulert areal. Liten påvirkning."
    return "unregulated", "Uregulert (NVE)."


nokken = json.loads((DATA / "reference" / "nokken_sections.json").read_text(encoding="utf-8"))
ww = json.loads((DATA / "reference" / "wwguide_sections_raw.json").read_text(encoding="utf-8"))
ww = ww["data"]["sections"]["nodes"]
existing = load_rivers()
have = {r["station"] for r in existing}
ids = {r["id"] for r in existing}
rivers_per_name = {}
for river, _ in SECTIONS.values():
    rivers_per_name[river] = rivers_per_name.get(river, 0) + 1

new = []
for st, (river, section) in SECTIONS.items():
    if st in have:
        continue
    s = next(x for x in nokken if x["station"] == st and x["river"] == river and x["section"] == section)
    d = hydapi._get("Stations", {"StationId": st})["data"][0]
    t = nokken_thresholds(s["bands"] or [])
    if t is None and st in WWGUIDE:
        w = next(x for x in ww if x["gauge"] and x["gauge"]["code"] + ".0" == st
                 and (x["river"]["name"], x["name"]) == WWGUIDE[st])
        t = {k: w["flows"][k] for k in ("minimum", "optimum", "maximum", "impossible")} | {"source": "whitewater.guide"}
    if t is None:
        print(f"{st} {river}: ingen terskler, hoppes over")
        continue
    rid = slug(river) if rivers_per_name[river] == 1 else f"{slug(river)}-{slug(section).split('-')[0]}"
    assert rid not in ids, rid
    ids.add(rid)
    reg, note = regulation(d)
    e = {"id": rid, "name": river if section == river else f"{river} – {section}",
         "station": st, "station_name": d["stationName"], "station_pos": [d["latitude"], d["longitude"]],
         "regulation": reg, "regulation_note": note, "grade": s["grade"], "approximate": st in PROXY,
         "thresholds": t, "nokken_river": int(s["river_id"]), "nokken_section": int(s["section_id"])}
    if s["putin"]:
        e["putin"] = s["putin"]
    if s["takeout"]:
        e["takeout"] = s["takeout"]
    new.append(e)
    print(f"{rid:24s} {st:10s} {reg:12s} {t['minimum']}-{t['optimum']}-{t['maximum']}-{t['impossible']} "
          f"{'(nabostasjon)' if st in PROXY else ''}")

if new:
    text = yaml.safe_dump(new, allow_unicode=True, sort_keys=False, width=200)
    with open(CONFIG / "rivers.yaml", "a", encoding="utf-8") as f:
        f.write(text)
print(len(new), "nye elver")
