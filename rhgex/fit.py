"""Option structures that fit the risk budget: long calls/puts and 1:1 debit verticals that pass the liquidity
rule, cost no more than the budget per contract, and pay at the plan's target.

Quotes come from Cboe's delayed chain (~15 min), so this is a shortlist: re-quote the pick on Robinhood
(`get_option_quotes`) and run `preflight` on the live numbers before `plan add`.
"""

import math
from datetime import date, datetime

from . import gex, preflight

DELTA_RANGE = (0.40, 0.65)  # the bought leg: at or slightly in the money
TOP = 10


def legs(data: dict, today: date, min_dte: int, max_dte: int) -> list[dict]:
    """Option legs from a Cboe chain within the expiry window, with a live two-sided quote."""
    out = []
    for o in data["options"]:
        m = gex.OCC.match(o["option"])
        bid, ask = o.get("bid") or 0, o.get("ask") or 0
        if not m or ask <= 0:
            continue
        exp = datetime.strptime(m["exp"], "%y%m%d").date()
        dte = (exp - today).days
        if min_dte <= dte <= max_dte:
            out.append({"expiry": exp.isoformat(), "dte": dte, "kind": "call" if m["cp"] == "C" else "put",
                        "strike": int(m["strike"]) / 1000, "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
                        "oi": int(o.get("open_interest") or 0), "delta": o.get("delta") or 0})
    return out


def _value_at(kind: str, strike: float, price: float) -> float:
    return max(price - strike, 0) if kind == "call" else max(strike - price, 0)


def candidates(rows: list[dict], direction: str, target: float, budget: float) -> list[dict]:
    """Every long single and debit vertical whose legs are liquid, costs <= budget per contract, and makes
    money at the target at expiry. Sorted by return at target, best first."""
    kind = "call" if direction == "bullish" else "put"
    beyond = (lambda a, b: a > b) if kind == "call" else (lambda a, b: a < b)  # further out of the money
    mine = [r for r in rows if r["kind"] == kind]
    liquid = {id(r): preflight.leg_liquidity(r["bid"], r["ask"], r["oi"])[0] for r in mine}
    short_ok = {id(r): preflight.leg_liquidity(r["bid"], r["ask"], r["oi"], short=True)[0] for r in mine}
    out = []

    def add(structure, long, short=None):
        debit = round(long["mid"] - (short["mid"] if short else 0), 2)
        cost = round(debit * 100, 2)
        if debit <= 0 or cost > budget:
            return
        value = _value_at(kind, long["strike"], target) - (_value_at(kind, short["strike"], target) if short else 0)
        if value <= debit:
            return
        out.append({"structure": structure, "expiry": long["expiry"], "dte": long["dte"],
                    "buy": long["strike"], "sell": short["strike"] if short else None,
                    "debit": debit, "cost_per_contract": cost,
                    "contracts": math.floor(budget / cost),
                    "max_value": round(abs(short["strike"] - long["strike"]) * 100, 2) if short else None,
                    "value_at_target": round(value * 100, 2), "return_at_target_pct": round((value / debit - 1) * 100),
                    "delta": long["delta"],
                    "legs": [f"{r['bid']},{r['ask']},{r['oi']}" for r in (long, short) if r]})

    for long in mine:
        if not (liquid[id(long)] and DELTA_RANGE[0] <= abs(long["delta"]) <= DELTA_RANGE[1]):
            continue
        add(kind, long)
        for short in mine:
            # the sold leg sits between the bought strike and the target (inclusive), same expiry
            if (short["expiry"] == long["expiry"] and short_ok[id(short)] and beyond(short["strike"], long["strike"])
                    and not beyond(short["strike"], target)):
                add(f"{kind} vertical", long, short)
    return sorted(out, key=lambda c: (-c["return_at_target_pct"], c["dte"]))


def scan(symbol: str, direction: str, target: float, budget: float, min_dte: int = 14, max_dte: int = 45,
         top: int = TOP) -> dict:
    data = gex.chain(symbol)
    rows = legs(data, date.today(), min_dte, max_dte)
    found = candidates(rows, direction, target, budget)
    return {"symbol": symbol.upper(), "spot": round(float(data["current_price"]), 2), "as_of": data.get("last_trade_time"),
            "direction": direction, "target": target, "budget": budget, "dte_window": [min_dte, max_dte],
            "found": len(found), "candidates": found[:top],
            "note": "delayed Cboe quotes: re-quote on Robinhood and run preflight before plan add"
            if found else "nothing fits: try another expiry window, the share fallback, or skip"}
