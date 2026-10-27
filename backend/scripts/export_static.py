"""Skriver API-svarene som statiske JSON-filer, slik at frontenden kan hostes uten server (GitHub Pages).

Bruk: python scripts/export_static.py [--out ../frontend/public]
Filene havner i <out>/api/... med samme stier som frontend/src/api.ts leser.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elvepred import api
from elvepred.settings import ROOT

p = argparse.ArgumentParser()
p.add_argument("--out", type=Path, default=ROOT / "frontend" / "public")
args = p.parse_args()
base = args.out / "api"


def write(path: str, data) -> None:
    f = base / f"{path}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


write("meta", api.meta())
rivers = api.rivers()
write("rivers", rivers)
for r in rivers:
    rid = r["id"]
    write(f"rivers/{rid}", api.river(rid))
    write(f"rivers/{rid}/observed_day", api.observed(rid, "day"))
    write(f"rivers/{rid}/observed_hour", api.observed(rid, "hour"))
    write(f"rivers/{rid}/forecast", api.forecast(rid))
    write(f"rivers/{rid}/forecast_hourly", api.forecast_hourly(rid))
print(f"skrev {len(list(base.rglob('*.json')))} filer til {base}")
