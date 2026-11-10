"""Kjører fetch_forecasts.py til alle stasjoner er hentet, og tåler at PC-en sover.

Etter dvale kan et kall til Open-Meteo henge uten å feile. Derfor stoppes og startes hentingen på nytt når loggen
har vært stille i STALE_MIN minutter. Når døgnkvoten er brukt opp, avslutter hentingen (--no-wait), og her ventes
det på veggklokka til kvoten nullstilles ved midnatt UTC.

    uv run python scripts/fetch_supervised.py
"""
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elvepred.settings import DATA, load_stations

STALE_MIN = 120  # en stasjon kan ta over en time, men skriver da 429-pauser til loggen
LOG = DATA / "fetch_forecasts_norge.log"
OUT = DATA / "raw" / "forecasts" / "metno_seamless"


def log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{msg} {pd.Timestamp.now(tz='UTC'):%Y-%m-%dT%H:%M:%SZ}\n")


def missing() -> int:
    return sum(not (OUT / f"{r['station']}.parquet").exists() for r in load_stations())


while missing():
    log("start")
    with LOG.open("a", encoding="utf-8") as f:
        p = subprocess.Popen([sys.executable, "-u", str(Path(__file__).with_name("fetch_forecasts.py")), "--no-wait"],
                             stdout=f, stderr=subprocess.STDOUT)
    while p.poll() is None:
        time.sleep(30)
        if time.time() - LOG.stat().st_mtime > STALE_MIN * 60:
            p.kill()
            p.wait()
            log(f"stille i {STALE_MIN} min, startes på nytt")
            break
    else:
        if "gnkvoten er brukt opp" in LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-1]:
            reset = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1, minutes=10)
            log(f"venter på døgnkvoten til {reset:%Y-%m-%d %H:%M} UTC")
            while pd.Timestamp.now(tz="UTC") < reset:  # veggklokke: tiden PC-en sover telles med
                time.sleep(60)
        elif p.returncode:
            time.sleep(300)  # krasj (f.eks. 30 nettbrudd på rad): prøv igjen om litt
log("alle stasjoner hentet")
