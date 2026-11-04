"""Henter ERA5 per time (Open-Meteo Historical Weather) rundt kraftige nedbørsdøgn før prognosearkivet.

Brukes til å fordele seNorge-døgnnedbøren på timer, så timesmodellen kan trenes på flommer tilbake til 1990
(hourly.truth_weather). Bare periodene rundt våte døgn hentes (hourly.era5_ranges): ca. 70 kall per stasjon.
Stasjonene i driftsmodellen hentes først. Deler gratiskvoten med fetch_forecasts.py og venter selv på den.

Skriver data/raw/era5/<stasjon>.parquet (rr, tm per time), og hopper over stasjoner som finnes.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import pandas as pd

from elvepred import hourly
from elvepred.clients import openmeteo
from elvepred.model.train import MODELS
from elvepred.settings import DATA, load_stations

WORKERS = 1  # Open-Meteo avviser samtidige kall («too many concurrent») når prognosehentingen også går

out = DATA / "raw" / "era5"
out.mkdir(parents=True, exist_ok=True)
first = joblib.load(MODELS / "h1_p50.joblib")["stations"]
stations = first + [r["station"] for r in load_stations() if r["station"] not in first]
for st in stations:
    f = out / f"{st}.parquet"
    if f.exists() or not (DATA / "raw" / "hydapi_hourly" / f"{st}.parquet").exists():
        continue
    t = time.time()
    g = pd.read_parquet(DATA / "raw" / "gts" / f"{st}.parquet")
    q = pd.read_parquet(DATA / "raw" / "hydapi_hourly" / f"{st}.parquet")["q"].dropna()
    ranges = hourly.era5_ranges(hourly.wet_days(g, max(q.index.min(), pd.Timestamp(hourly.HISTORY_START))))
    with ThreadPoolExecutor(WORKERS) as ex:
        parts = list(ex.map(lambda r: openmeteo.era5_hourly(st, f"{r[0]:%Y-%m-%d}", f"{r[1]:%Y-%m-%d}"), ranges))
    df = pd.concat(parts) if parts else pd.DataFrame(columns=["rr", "tm"], dtype=float)
    df[~df.index.duplicated()].sort_index().to_parquet(f)
    print(f"{st:10s} {len(ranges)} perioder, {len(df)} timer ({time.time() - t:.0f}s)", flush=True)
