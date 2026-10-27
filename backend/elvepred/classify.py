"""Padlestatus i whitewater.guide-semantikk (intervallene fra getSectionColor)."""
import math

LABELS = ["dry", "low", "min-opt", "opt-max", "high", "impossible"]


def dry_level(t: dict) -> float:
    mn, opt, mx, imp = (t.get(k) for k in ("minimum", "optimum", "maximum", "impossible"))
    if mn is None:
        return math.nan
    if opt is not None:
        return mn - (opt - mn) / 5
    if mx is not None:
        return mn - (mx - mn) / 10
    if imp is not None:
        return mn - (imp - mn) / 20
    return 0.7 * mn


def interval(q: float, t: dict) -> int:
    """0 tørr, 1 under min, 2 min–opt, 3 opt–max, 4 max–umulig, 5 over umulig."""
    if q is None or math.isnan(q):
        return -1
    edges = [dry_level(t), t.get("minimum"), t.get("optimum"), t.get("maximum"), t.get("impossible")]
    i = 0
    for e in edges:
        if e is not None and not math.isnan(e) and q >= e:
            i += 1
        elif e is not None:
            break
        else:
            i += 1  # manglende terskel hoppes over
    return i


def paddleable(q: float, t: dict) -> bool:
    return t["minimum"] <= q < t["maximum"]


def optimal(q: float, t: dict) -> bool:
    return t["optimum"] <= q < t["maximum"]


_Z90 = 1.2815515655446004  # standardnormalens 90-persentil


def _cdf(q: float, p10: float, p50: float, p90: float) -> float:
    """P(Q < q) fra delt lognormal tilpasset p10/p50/p90 (egen bredde under og over medianen)."""
    if q <= 0:
        return 0.0
    lo, mid, hi = (math.log(max(v, 1e-6)) for v in (p10, p50, p90))
    x = math.log(q) - mid
    s = max((mid - lo) if x < 0 else (hi - mid), 1e-6) / _Z90
    return 0.5 * (1 + math.erf(x / (s * math.sqrt(2))))


def prob_between(a: float, b: float, p10: float, p50: float, p90: float) -> float:
    return max(0.0, _cdf(b, p10, p50, p90) - _cdf(a, p10, p50, p90))
