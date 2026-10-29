import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA = ROOT / "data"
CONFIG = BACKEND / "config"

load_dotenv(ROOT / ".env")

NVE_API_KEY = os.environ.get("NVE_API_KEY", "")


def load_rivers() -> list[dict]:
    with open(CONFIG / "rivers.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["rivers"]


def load_stations() -> list[dict]:
    """Første (primære) seksjon per målestasjon. Modellene trenes og evalueres per stasjon."""
    out = {}
    for r in load_rivers():
        out.setdefault(r["station"], r)
    return list(out.values())
