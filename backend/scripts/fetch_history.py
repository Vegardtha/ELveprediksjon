"""Henter historisk vannføring (HydAPI) og feltmiddel vær/snø/HBV (GTS) for alle elver."""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from elvepred.clients import gts, hydapi
from elvepred.settings import DATA, load_rivers

p = argparse.ArgumentParser()
p.add_argument("--from", dest="start", default="1990-01-01")
p.add_argument("--river")
args = p.parse_args()

today = pd.Timestamp.today().normalize()
(DATA / "raw" / "hydapi").mkdir(parents=True, exist_ok=True)
(DATA / "raw" / "gts").mkdir(parents=True, exist_ok=True)

for r in load_rivers():
    if args.river and r["id"] != args.river:
        continue
    st = r["station"]
    t = time.time()
    q = hydapi.daily_discharge(st, args.start, today.strftime("%Y-%m-%d"))
    q.to_parquet(DATA / "raw" / "hydapi" / f"{st}.parquet")
    t_q = time.time() - t
    t = time.time()
    w = gts.frame(st, args.start, (today - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    w.to_parquet(DATA / "raw" / "gts" / f"{st}.parquet")
    print(f"{r['id']:12s} {st:9s} Q: {len(q):6d} d fra {q.index.min().date()} ({t_q:.1f}s)  "
          f"GTS: {len(w):6d} d ({time.time() - t:.1f}s)")
