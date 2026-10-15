"""The source's calls, scored (private/logs/calls.json): did price reach his target before his invalidation?

Each directional post becomes one call: the level it's made from, a target, the price that proves it wrong,
a deadline, and a setup type. `calls check` scores open calls on daily highs and lows since the post; `calls
stats` gives the hit rate by setup type, so trust in each kind of call comes from his record, not memory.
A day that touches both the target and the invalidation counts as a fail (no intraday order to tell).
A call posted during the session is scored on its post day only from the post time on (5-minute bars), so a
move made before he posted can't count for or against him.
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
    """posted: 'YYYY-MM-DD HH:MM' in this computer's local time (the post note's name), or a date alone for a
    post made before the open. Default: now."""
    if direction not in ("bullish", "bearish"):
        raise ValueError("direction must be bullish or bearish")
    if setup not in SETUPS:
        raise ValueError(f"setup must be one of {', '.join(SETUPS)}")
    bull = direction == "bullish"
    if (bull and not invalid < target) or (not bull and not invalid > target):
        raise ValueError(f"a {direction} call needs the invalidation {'below' if bull else 'above'} the target")
    posted_at = datetime.fromisoformat(posted) if posted and len(posted) > 10 else None if posted else datetime.now()
    posted_d = posted_at.date() if posted_at else date.fromisoformat(posted)
    by_d = date.fromisoformat(by) if by else add_trading_days(posted_d, DEFAULT_DAYS)
    if by_d < posted_d:
        raise ValueError("--by is before the post date")
    calls = load(path)
    if any(c["source"] == source and c["symbol"] == symbol.upper() for c in calls):
        raise ValueError(f"{symbol.upper()} from this post is already logged")
    c = {"symbol": symbol.upper(), "direction": direction, "setup": setup, "level": level, "target": target,
         "invalid": invalid, "posted": posted_d.isoformat(), "by": by_d.isoformat(), "source": source,
         "note": note, "result": "open", "logged": datetime.now().isoformat(timespec="seconds")}
    if posted_at:
        c["posted_at"] = posted_at.isoformat(timespec="minutes")
    calls.append(c)
    save(calls, path)
    return c


def score(call: dict, bars: list[tuple[date, float, float]], today: date,
          post_day: tuple[float, float] | None = None) -> tuple[str, str | None]:
    """bars: daily (day, high, low) from the post date on. post_day: (high, low) after the post time on the post
    day, for a call with posted_at; without it that day is skipped. Returns (result, the day it resolved)."""
    bull = call["direction"] == "bullish"
    posted = date.fromisoformat(call["posted"])
    for day, high, low in bars:
        if day < posted or day > date.fromisoformat(call["by"]):
            continue
        if day == posted and call.get("posted_at"):
            if post_day is None:
                continue
            high, low = post_day
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


def after_post(symbol: str, posted_at: str) -> tuple[float, float] | None:
    """High and low of the post day's regular session from the post time on, or None (no bars yet, or too old for
    Yahoo's 60-day 5-minute history)."""
    from .market import yahoo_symbol
    import yfinance as yf

    at = datetime.fromisoformat(posted_at).astimezone()  # local time, as the post notes are named
    try:
        h = yf.Ticker(yahoo_symbol(symbol)).history(start=at.date(), end=at.date() + timedelta(days=1),
                                                    interval="5m", prepost=False, auto_adjust=False)
    except Exception:
        return None
    h = h[h.index >= at - timedelta(minutes=5)]  # the 5-minute bar the post landed in counts
    return (float(h["High"].max()), float(h["Low"].min())) if len(h) else None


def check(today: date | None = None, path: Path = CALLS, bars=daily_bars, after=after_post) -> list[dict]:
    """Score every open call; resolved ones keep their result."""
    today = today or date.today()
    calls = load(path)
    changed = []
    for c in calls:
        if c["result"] != "open":
            continue
        post_day = after(c["symbol"], c["posted_at"]) if c.get("posted_at") else None
        result, day = score(c, bars(c["symbol"], c["posted"]), today, post_day)
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
