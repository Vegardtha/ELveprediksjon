import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from elvepred.model.predict import predict_all

out, timing = predict_all()
pd.set_option("display.width", 200)
print(out[["river", "date", "q_now", "p10", "p50", "p90", "status", "rr_forecast"]].round(1).to_string(index=False))
print(timing)
