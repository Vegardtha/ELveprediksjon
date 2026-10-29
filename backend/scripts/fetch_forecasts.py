"""Henter arkiverte værprognoser (Open-Meteo Previous Runs) per nedbørfelt."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse

import pandas as pd

from elvepred.clients import openmeteo
from elvepred.settings import DATA, load_stations

p = argparse.ArgumentParser()
p.add_argument("--models", default="metno_seamless")
p.add_argument("--refresh", action="store_true", help="hent på nytt også for stasjoner som finnes")
p.add_argument("--no-wait", action="store_true", help="stopp når døgnkvoten er brukt opp i stedet for å vente til neste døgn")
args = p.parse_args()
MODELS = args.models.split(",")
end = (pd.Timestamp.today().normalize() + pd.Timedelta(days=8)).strftime("%Y-%m-%d")
for model in MODELS:
    out = DATA / "raw" / "forecasts" / model
    out.mkdir(parents=True, exist_ok=True)
    for r in load_stations():
        if not args.refresh and (out / f"{r['station']}.parquet").exists():
            continue
        t = time.time()
        try:
            h = openmeteo.hourly(r["station"], model, openmeteo.ARCHIVE_START, end, wait_daily=not args.no_wait)
        except openmeteo.DailyQuotaExceeded:
            print(f"døgnkvoten er brukt opp ved {r['station']}; resten hentes ved neste kjøring", flush=True)
            sys.exit(0)
        h.to_parquet(out / f"{r['station']}_hourly.parquet")
        d = openmeteo.daily_forecasts(h)
        d.to_parquet(out / f"{r['station']}.parquet")
        print(f"{model:15s} {r['id']:12s} {len(h)} timer, {d['rr_fc2'].notna().sum()} dager ({time.time() - t:.0f}s)", flush=True)
