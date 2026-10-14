"""Rough gamma exposure (GEX) profile from Cboe's free delayed option chains (~15 min delay).

Uses the common naive dealer assumption: dealers are long the calls and short the puts that customers
hold, so call gamma counts positive and put gamma negative. Real dealer positioning differs, so treat this
as a cross-check on the X account's levels, not as ground truth. Open interest updates once a day.
"""

import json
import math
import re
import urllib.request
from datetime import date, datetime

CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{}.json"
INDICES = {"SPX", "XSP", "NDX", "RUT", "VIX", "DJX"}
OCC = re.compile(r"^(?P<root>[A-Z]+)(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
RISK_FREE = 0.04
CONTRACT = 100


def bs_gamma(spot: float, strike: float, iv: float, years: float) -> float:
    if iv <= 0 or years <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (RISK_FREE + iv * iv / 2) * years) / (iv * math.sqrt(years))
    return math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi) / (spot * iv * math.sqrt(years))


def chain(symbol: str) -> dict:
    sym = symbol.upper().lstrip("^$")
    url = CBOE.format(f"_{sym}" if sym in INDICES else sym)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["data"]


def _contracts(data: dict, max_days: int, roots: set[str] | None) -> list[dict]:
    today = date.today()
    rows = []
    for o in data["options"]:
        m = OCC.match(o["option"])
        oi, iv = o.get("open_interest") or 0, o.get("iv") or 0
        if not m or oi <= 0 or iv < 0.01 or (roots and m["root"] not in roots):
            continue
        exp = datetime.strptime(m["exp"], "%y%m%d").date()
        days = (exp - today).days
        if days < 0 or days > max_days:
            continue
        rows.append({"kind": "call" if m["cp"] == "C" else "put", "strike": int(m["strike"]) / 1000,
                     "expiry": exp.isoformat(), "oi": oi, "iv": iv, "gamma": o.get("gamma") or 0,
                     "years": max(days, 0.5) / 365})  # 0DTE still carries a little time until the close
    return rows


def _dollar_gamma(gamma: float, oi: float, spot: float) -> float:
    # Dollar gamma per 1% move: gamma * OI * 100 * S^2 * 1%.
    return gamma * oi * CONTRACT * spot * spot * 0.01


def _total_at(rows: list[dict], spot: float) -> float:
    return sum((1 if r["kind"] == "call" else -1)
               * _dollar_gamma(bs_gamma(spot, r["strike"], r["iv"], r["years"]), r["oi"], spot) for r in rows)


def profile(symbol: str, max_days: int = 45, roots: set[str] | None = None) -> dict:
    data = chain(symbol)
    spot = float(data["current_price"])
    rows = _contracts(data, max_days, roots)
    if not rows:
        return {"symbol": symbol, "error": "no option chain data with open interest"}

    by_strike: dict[float, dict] = {}
    for r in rows:
        s = by_strike.setdefault(r["strike"], {"call": 0.0, "put": 0.0})
        s[r["kind"]] += _dollar_gamma(r["gamma"], r["oi"], spot)
    net = {k: v["call"] - v["put"] for k, v in by_strike.items()}
    total = sum(net.values())

    # Zero-gamma flip: re-price total GEX across a +/-15% spot grid and find the sign change nearest spot.
    grid = [spot * (0.85 + i * 0.005) for i in range(61)]
    totals = [_total_at(rows, s) for s in grid]
    flips = [grid[i] + (grid[i + 1] - grid[i]) * totals[i] / (totals[i] - totals[i + 1])
             for i in range(len(grid) - 1) if totals[i] * totals[i + 1] < 0]
    flip = min(flips, key=lambda f: abs(f - spot)) if flips else None

    near = {k: v for k, v in by_strike.items() if abs(k / spot - 1) <= 0.10}
    return {
        "symbol": symbol.upper(),
        "spot": round(spot, 2),
        "as_of": data.get("last_trade_time"),
        "iv30": data.get("iv30"),
        "days_included": max_days,
        "contracts_used": len(rows),
        "total_gex_usd_per_1pct": round(total),
        "regime": "positive gamma (dealers dampen moves)" if total > 0 else "negative gamma (dealers amplify moves)",
        "zero_gamma_flip": round(flip, 2) if flip else None,
        "call_wall_within_10pct": max(near, key=lambda k: near[k]["call"]) if near else None,
        "put_wall_within_10pct": max(near, key=lambda k: near[k]["put"]) if near else None,
        "top_strikes_within_10pct": [
            {"strike": k, "net_gex": round(net[k])}
            for k in sorted(near, key=lambda k: abs(net[k]), reverse=True)[:8]
        ],
    }
