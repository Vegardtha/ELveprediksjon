"""Henter timesverdier vannføring (HydAPI) for alle elver – brukes til nowcast-features."""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from elvepred.clients import hydapi
from elvepred.settings import DATA, load_rivers

out = DATA / "raw" / "hydapi_hourly"
out.mkdir(parents=True, exist_ok=True)
today = pd.Timestamp.today().normalize()


def fetch(r):
    t = time.time()
    q = hydapi.hourly_discharge(r["station"], "1990-01-01", today.strftime("%Y-%m-%d"))
    q.to_frame().to_parquet(out / f"{r['station']}.parquet")
    return f"{r['id']:12s} {len(q):7d} timer, {q.notna().sum():7d} med verdi, fra {q.first_valid_index()} ({time.time() - t:.0f}s)"


with ThreadPoolExecutor(1) as ex:
    for line in ex.map(fetch, load_rivers()):
        print(line)
