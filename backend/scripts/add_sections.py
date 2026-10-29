"""Legger alle padleseksjoner med nivåer på Østlandet inn i config/rivers.yaml, fra nokken.net og whitewater.guide.

Én målestasjon kan ha mange seksjoner; prognosen er per stasjon, mens terskler, innsett/utsett og grad er per
seksjon. Første oppføring per stasjon er «primær» (den evalueres). Seksjoner som allerede finnes hoppes over:
nokken-seksjoner på nokken_section, whitewater.guide-seksjoner på wwguide_section eller på normalisert
(elv, seksjon) mot det som allerede ligger på samme stasjon.

Terskler fra nokken (LOW.min → minimum, GOOD → optimum..maximum, VERY HIGH.min eller HIGH.max → impossible),
ellers whitewater.guide (flows). Regulering fra HydAPI Stations.

Krever data/reference/nokken_sections.json (scripts/fetch_nokken.py) og data/reference/wwguide_sections_raw.json
(svaret på GraphQL-spørringen `sections(filter:{regionId}, page:{limit:1000})` mot https://api.whitewater.guide/graphql
med feltene id, name, difficulty, river.name, gauge.code, flows, putIn.coordinates og takeOut.coordinates).
Deretter: fetch_catchments.py, fetch_history.py --new, fetch_hourly.py --new, fetch_forecasts.py og ny trening.
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

# Østlandet: hovedvassdrag 1–16 (Glomma til Skiensvassdraget) og Femund/Trysil (311)
OSTLANDET = set(range(1, 17)) | {311}
# målestasjonen står i en annen (nabo)elv enn seksjonen, selv om elvenavnet er likt
PROXY = {"12.171.0", "12.215.0", "311.460.0"}
# Glomma ved Solbergfoss: 40 000 km², styrt av magasinslipp og uten nedbørfelt i NVEs kart (trengs for GTS).
# Pæddekummen ligger derfor inne for hånd med `forecast: false` (bare målt vannføring).
EXCLUDE = {"2.605.0"}
# målestasjonen står i seksjonens elv selv om HydAPI bruker vassdrags- eller stedsnavn
PRIMARY = {"12.164.0": "Usteåni", "12.76.0": "Storåni", "16.10.0": "Hedølla"}
# whitewater.guide-seksjoner som er samme strekning som en nokken-seksjon med annet navn
SKIP_WW = {("Otta", "Skjåk Playspot"), ("Lågen", "Rosten"), ("Sjoa", "Playrun"), ("Akerselva", "Oslo ditch")}
GENERIC = {"main", "normal", "standard"}


def slug(s: str) -> str:
    s = s.lower().replace("ø", "o").replace("æ", "ae").replace("å", "a")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def key(river: str, section: str) -> tuple[str, str]:
    r, s = slug(river).replace("-", ""), slug(section).replace("-", "")
    return r, "main" if s in GENERIC or s == r else s


def station_id(code: str) -> str:
    return ".".join((code.split(".") + ["0"])[:2]) + ".0"


def grade(d: float | None) -> str | None:
    if not d:
        return None
    roman = ["", "I", "II", "III", "IV", "V", "VI"]
    return roman[int(d)] if d == int(d) else f"{roman[int(d)]}–{roman[int(d) + 1]}"


def nokken_thresholds(bands: list[dict]) -> dict | None:
    b = {x["label"]: x for x in bands}
    if "GOOD" not in b:
        return None
    good = b["GOOD"]
    hi = b.get("VERY HIGH", {}).get("min") or b.get("HIGH", {}).get("max") or good["max"]
    t = {"minimum": b.get("LOW", good)["min"], "optimum": good["min"], "maximum": good["max"], "impossible": hi}
    return {k: round(v, 1) for k, v in t.items()} | {"source": "nokken.net"}


def ww_thresholds(f: dict | None) -> dict | None:
    if not f or f.get("minimum") is None or f.get("maximum") is None:
        return None
    lo, hi = f["minimum"], f["maximum"]
    opt = f.get("optimum") if f.get("optimum") is not None else lo
    imp = f.get("impossible") if f.get("impossible") is not None else hi
    if not lo <= opt <= hi <= imp:
        return None
    return {"minimum": lo, "optimum": opt, "maximum": hi, "impossible": imp, "source": "whitewater.guide"}


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


def candidates() -> dict[str, list[dict]]:
    """Seksjoner med nivåer per stasjon: nokken først, så whitewater.guide."""
    out = {}
    for x in json.loads((DATA / "reference" / "nokken_sections.json").read_text(encoding="utf-8")):
        if not x["station"] or int(x["station"].split(".")[0]) not in OSTLANDET:
            continue
        t = nokken_thresholds(x["bands"] or [])
        if t:
            out.setdefault(station_id(x["station"]), []).append({
                "river": x["river"], "section": x["section"], "grade": x["grade"], "thresholds": t,
                "putin": x["putin"], "takeout": x["takeout"],
                "nokken_river": int(x["river_id"]), "nokken_section": int(x["section_id"])})
    ww = json.loads((DATA / "reference" / "wwguide_sections_raw.json").read_text(encoding="utf-8"))
    for x in ww["data"]["sections"]["nodes"]:
        river = x["river"]["name"].strip()
        if not x["gauge"] or int(x["gauge"]["code"].split(".")[0]) not in OSTLANDET or (river, x["name"]) in SKIP_WW:
            continue
        t = ww_thresholds(x["flows"])
        pos = lambda p: [round(p["coordinates"][1], 6), round(p["coordinates"][0], 6)] if p else None
        if t:
            out.setdefault(station_id(x["gauge"]["code"]), []).append({
                "river": river, "section": x["name"].strip(), "grade": grade(x["difficulty"]), "thresholds": t,
                "putin": pos(x["putIn"]), "takeout": pos(x["takeOut"]), "wwguide_section": x["id"]})
    return out


existing = load_rivers()
ids = {r["id"] for r in existing}
nokken_have = {r["nokken_section"] for r in existing if r.get("nokken_section")}
ww_have = {r["wwguide_section"] for r in existing if r.get("wwguide_section")}
by_station = {}
for r in existing:
    by_station.setdefault(r["station"], []).append(r)
keys = {(r["station"], key(*(r["name"].split(" – ") + [r["name"]])[:2])) for r in existing}

new, info = [], {}
for st, secs in candidates().items():
    if st in EXCLUDE:
        continue
    secs = [s for s in secs if s.get("nokken_section", 0) not in nokken_have and s.get("wwguide_section", "") not in ww_have]
    secs = [s for s in secs if (st, key(s["river"], s["section"])) not in keys]
    if not secs:
        continue
    if st not in info:
        try:
            info[st] = hydapi._get("Stations", {"StationId": st})["data"][0]
        except (IndexError, Exception) as e:
            print(f"{st}: ikke i HydAPI ({type(e).__name__}), hoppes over")
            continue
    d = info[st]
    if not any(s["parameter"] == 1001 for s in d.get("seriesList", [])):
        print(f"{st}: ingen vannføring, hoppes over")
        continue
    reg, note = regulation(d)
    here = by_station.setdefault(st, [])
    # primær elv: den som allerede er lagt inn, ellers seksjonen som ligger i elva målestasjonen står i
    if here:
        primary_river = slug(here[0]["name"].split(" – ")[0])
        primary_proxy = here[0].get("approximate", False)
    else:
        gauge_names = slug(d["riverName"] + " " + d["stationName"])
        hit = next((s for s in secs if s["river"] == PRIMARY.get(st)
                    or slug(s["river"]).split("-")[0][:5] in gauge_names), None)
        primary_river = slug(hit["river"]) if hit else None
        primary_proxy = hit is None or st in PROXY
        if hit:
            secs.remove(hit)
            secs.insert(0, hit)
    for s in secs:
        k = key(s["river"], s["section"])
        if (st, k) in keys:  # duplikat mellom nokken og whitewater.guide
            continue
        keys.add((st, k))
        name = s["river"] if k[1] == "main" else f"{s['river']} – {s['section']}"
        rid = slug(name)
        while rid in ids:
            rid += "-2"
        ids.add(rid)
        e = {"id": rid, "name": name, "station": st, "station_name": d["stationName"],
             "station_pos": [d["latitude"], d["longitude"]], "regulation": reg, "regulation_note": note,
             "grade": s["grade"], "approximate": primary_proxy or slug(s["river"]) != primary_river,
             "thresholds": s["thresholds"]}
        e |= {f: s[f] for f in ("nokken_river", "nokken_section", "wwguide_section", "putin", "takeout") if s.get(f)}
        here.append(e)
        new.append(e)
        t = e["thresholds"]
        print(f"{st:10s} {rid:36s} {reg:11s} {t['minimum']}-{t['optimum']}-{t['maximum']}-{t['impossible']} "
              f"{t['source'][:6]}{' ~' if e['approximate'] else ''}")

if "--dry-run" not in sys.argv and new:
    text = yaml.safe_dump(new, allow_unicode=True, sort_keys=False, width=200)
    with open(CONFIG / "rivers.yaml", "a", encoding="utf-8") as f:
        f.write(text)
print(len(new), "nye seksjoner,", len({e["station"] for e in new} - {r["station"] for r in existing}), "nye stasjoner")
