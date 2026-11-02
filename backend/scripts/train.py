import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib

from elvepred.model.train import MODELS, train_all

# --same-stations: samme stasjoner som modellene som ligger der nå, ellers alle med komplett rådata
same = "--same-stations" in sys.argv
print(train_all(joblib.load(MODELS / "h1_p50.joblib")["stations"] if same else None))
