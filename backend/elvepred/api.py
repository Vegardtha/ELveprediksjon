"""HTTP-API for webappen. Leser siste kjøring fra data/predictions (skrevet av scripts/update.py).

Start: uv run uvicorn elvepred.api:app --reload
"""
import json
import math

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from elvepred import classify
from elvepred.model.predict import OUT
from elvepred.settings import DATA, ROOT, load_rivers

METRICS_KEY = "wx_mixed/metno_seamless | real metno_seamless"
ATTRIBUTION = [
    {"name": "NVE HydAPI", "what": "vannføring", "license": "NLOD 2.0", "url": "https://hydapi.nve.no"},
    {"name": "NVE/MET seNorge (GTS)", "what": "observert nedbør, temperatur, snø og HBV-tilstand",
     "license": "CC BY 4.0", "url": "https://www.senorge.no"},
    {"name": "MET Norway via Open-Meteo", "what": "værprognose", "license": "CC BY 4.0",
     "url": "https://open-meteo.com"},
    {"name": "nokken.net", "what": "padlenivåer og innsett/utsett", "license": "CC BY-NC-SA 4.0",
     "url": "https://nokken.net"},
    {"name": "whitewater.guide", "what": "padlenivåer", "license": "CC BY-NC-SA 4.0",
     "url": "https://whitewater.guide"},
]

app = FastAPI(title="Elvepred")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["GET"])

_cache: dict = {}


def _load() -> dict:
    """Parquet-filene leses på nytt når update.py har skrevet en ny kjøring."""
    run = OUT / "run.json"
    mtime = run.stat().st_mtime if run.exists() else 0
    if _cache.get("mtime") != mtime:
        metrics_path = DATA / "eval" / "metrics_fc.json"
        hourly_path = DATA / "eval" / "metrics_hourly.json"
        _cache.update(
            mtime=mtime,
            run=json.loads(run.read_text()) if run.exists() else {},
            rivers={r["id"]: r for r in load_rivers()},
            fc=pd.read_parquet(OUT / "latest.parquet"),
            obs=pd.read_parquet(OUT / "observed.parquet") if (OUT / "observed.parquet").exists() else None,
            hourly=pd.read_parquet(OUT / "hourly.parquet") if (OUT / "hourly.parquet").exists() else None,
            metrics=json.loads(metrics_path.read_text())["results"] if metrics_path.exists() else {},
            metrics_hourly=json.loads(hourly_path.read_text())["results"] if hourly_path.exists() else {},
        )
    return _cache


def _clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def _river(rid: str) -> dict:
    r = _load()["rivers"].get(rid)
    if r is None:
        raise HTTPException(404, f"ukjent elv {rid}")
    return r


def _summary(r: dict, fc: pd.DataFrame) -> dict:
    t = r["thresholds"]
    f = fc[fc["river"] == r["id"]].sort_values("date")
    q_now = float(f["q_now"].iloc[0]) if len(f) else None
    return {
        "id": r["id"], "name": r["name"], "grade": r.get("grade"), "station": r["station"],
        "station_name": r.get("station_name"),
        "regulation": r.get("regulation", "unknown"), "regulation_note": r.get("regulation_note"),
        "approximate": bool(r.get("approximate")),
        "thresholds": {k: t.get(k) for k in ("minimum", "optimum", "maximum", "impossible", "source")},
        "putin": r.get("putin"), "takeout": r.get("takeout"), "station_pos": r.get("station_pos"),
        "nokken_url": f"https://nokken.net/rivers/{r['nokken_river']}" if r.get("nokken_river") else None,
        "q_now": q_now,
        "q_now_time": _clean(f["q_now_time"].iloc[0]) if len(f) else None,
        "status_now": classify.LABELS[classify.interval(q_now, t)] if q_now is not None else None,
        "days": _records(f[["date", "p10", "p50", "p90", "status", "prob_paddleable", "prob_optimal"]]),
    }


@app.get("/api/meta")
def meta():
    d = _load()
    return {"run": d["run"], "issue_date": _clean(d["fc"]["issue_date"].max()), "attribution": ATTRIBUTION}


@app.get("/api/rivers")
def rivers():
    d = _load()
    return [_summary(r, d["fc"]) for r in d["rivers"].values()]


@app.get("/api/rivers/{rid}")
def river(rid: str):
    r = _river(rid)
    d = _load()
    m = d["metrics"]
    skill = [{"horizon": int(h), **{k: m[h][METRICS_KEY][rid].get(k) for k in ("NSE", "F1_paddleable")}}
             for h in sorted(m, key=int) if rid in m[h].get(METRICS_KEY, {})]
    mh = d["metrics_hourly"]
    skill_hourly = [{"hours": int(k), "NSE": v["model"][rid]["NSE"], "NSE_persistence": v["persistence"][rid]["NSE"]}
                    for k, v in sorted(mh.items(), key=lambda x: int(x[0])) if rid in v["model"]]
    return {**_summary(r, d["fc"]), "skill": skill, "skill_hourly": skill_hourly}


@app.get("/api/rivers/{rid}/observed")
def observed(rid: str, resolution: str = "day"):
    _river(rid)
    obs = _load()["obs"]
    if obs is None:
        return []
    o = obs[(obs["river"] == rid) & (obs["resolution"] == resolution)]
    return _records(o[["time", "q"]].sort_values("time"))


@app.get("/api/rivers/{rid}/forecast")
def forecast(rid: str):
    _river(rid)
    fc = _load()["fc"]
    f = fc[fc["river"] == rid].sort_values("date")
    cols = ["issue_date", "date", "horizon", "p10", "p50", "p90", "status", "prob_paddleable", "prob_optimal",
            "rr_forecast", "tm_forecast"]
    return _records(f[[c for c in cols if c in f]])


@app.get("/api/rivers/{rid}/forecast/hourly")
def forecast_hourly(rid: str):
    _river(rid)
    h = _load()["hourly"]
    if h is None:
        return []
    f = h[h["river"] == rid].sort_values("time")
    return _records(f[["issue_time", "time", "k", "p10", "p50", "p90", "status", "prob_paddleable", "rr"]])


# Bygget frontend (npm run build) serveres fra samme prosess i drift
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
