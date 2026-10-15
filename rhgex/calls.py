"""The source's calls, scored (private/logs/calls.json): did price reach his target before his invalidation?

Each directional post becomes one call: the level it's made from, a target, the price that proves it wrong,
a deadline, and a setup type. `calls check` scores open calls on daily highs and lows since the post; `calls
stats` gives the hit rate by setup type, so trust in each kind of call comes from his record, not memory.
A day that touches both the target and the invalidation counts as a fail (no intraday order to tell).
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import paths

CALLS = paths.LOGS / "calls.json"
SETUPS = ("uptrend-dip", "downtrend-dip", "breakdown", "breakout", "range", "other")
DEFAULT_DAYS = 5  # trading days for a call to play out when he gives no date


def add_trading_days(day: date, n: int) -> date:
    while n > 0:
        day += timedelta(days=1)
        n -= day.weekday() < 5
    return day


def load(path: Path = CALLS) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def save(calls: list[dict], path: Path = CALLS) -> None:
    paths.ensure(path.parent)
    path.write_text(json.dumps(calls, indent=2))


def add(symbol: str, direction: str, setup: str, level: float, target: float, invalid: float, source: str,
        by: str | None = None, posted: str | None = None, note: str = "", path: Path = CALLS) -> dict:
    if direction not in ("bullish", "bearish"):
        raise ValueError("direction must be bullish or bearish")
    if setup not in SETUPS:
        raise ValueError(f"setup must be one of {', '.join(SETUPS)}")
    bull = direction == "bullish"
    if (bull and not invalid < target) or (not bull and not invalid > target):
        raise ValueError(f"a {direction} call needs the invalidation {'below' if bull else 'above'} the target")
    posted_d = date.fromisoformat(posted) if posted else date.today()
    by_d = date.fromisoformat(by) if by else add_trading_days(posted_d, DEFAULT_DAYS)
    if by_d < posted_d:
        raise ValueError("--by is before the post date")
    calls = load(path)
    if any(c["source"] == source and c["symbol"] == symbol.upper() for c in calls):
        raise ValueError(f"{symbol.upper()} from this post is already logged")
    c = {"symbol": symbol.upper(), "direction": direction, "setup": setup, "level": level, "target": target,
         "invalid": invalid, "posted": posted_d.isoformat(), "by": by_d.isoformat(), "source": source,
         "note": note, "result": "open", "logged": datetime.now().isoformat(timespec="seconds")}
    calls.append(c)
    save(calls, path)
    return c


def score(call: dict, bars: list[tuple[date, float, float]], today: date) -> tuple[str, str | None]:
    """bars: (day, high, low) from the post date on. Returns (result, the day it resolved)."""
    bull = call["direction"] == "bullish"
    for day, high, low in bars:
        if day < date.fromisoformat(call["posted"]) or day > date.fromisoformat(call["by"]):
            continue
        failed = low <= call["invalid"] if bull else high >= call["invalid"]
        hit = high >= call["target"] if bull else low <= call["target"]
        if failed:
            return "fail", day.isoformat()
        if hit:
            return "hit", day.isoformat()
    return ("expired", call["by"]) if today > date.fromisoformat(call["by"]) else ("open", None)


def daily_bars(symbol: str, start: str) -> list[tuple[date, float, float]]:
    from .market import yahoo_symbol
    import yfinance as yf

    h = yf.Ticker(yahoo_symbol(symbol)).history(start=start, auto_adjust=False)
    return [(d.date(), float(r.High), float(r.Low)) for d, r in h.iterrows()]


def check(today: date | None = None, path: Path = CALLS, bars=daily_bars) -> list[dict]:
    """Score every open call; resolved ones keep their result."""
    today = today or date.today()
    calls = load(path)
    changed = []
    for c in calls:
        if c["result"] != "open":
            continue
        result, day = score(c, bars(c["symbol"], c["posted"]), today)
        if result != "open":
            c.update(result=result, resolved=day)
            changed.append(c)
    if changed:
        save(calls, path)
    return changed


def stats(calls: list[dict]) -> dict:
    """Hit rate by setup type and direction, over resolved calls (expired ones count as misses)."""
    out: dict[str, dict] = {}
    for c in calls:
        for key in (c["setup"], f"all {c['direction']}"):
            s = out.setdefault(key, {"hit": 0, "fail": 0, "expired": 0, "open": 0})
            s[c["result"]] += 1
    for s in out.values():
        done = s["hit"] + s["fail"] + s["expired"]
        s["hit_rate"] = round(s["hit"] / done, 2) if done else None
    return out
