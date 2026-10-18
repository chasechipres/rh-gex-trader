"""The watcher: a price loop with no model in it, run between exit checks so the session wakes only when needed.

`rhgex monitor` polls Yahoo quotes every minute during regular hours and exits as soon as something needs Claude,
printing one JSON line per event:

- WATCH_TRIGGERED: an open watch's trigger is crossed (the same test as `watch check`)
- RECLAIM_CONFIRMED / RECLAIM_INVALIDATED: a reclaim watch (`watch add --reclaim`) got its 15-minute close back
  above the level on above-average volume after touching it, or traded through its stop first
- STOP_HIT, TARGET_HIT, AT_1R: an open plan's level, on the underlying (a leveraged fund is tracked on its stock)
- SAME_DAY_EXIT: a `[reclaim]` position is still open at 15:45 ET

It also exits, with one final line, when there's nothing to watch (IDLE), at the end of its heartbeat
(HEARTBEAT, `--minutes`), at the close (CLOSED), or when quotes stop coming (FEED_DOWN): a watcher that has
stopped never looks like a quiet market. Run it in the background; its exit wakes the session, which confirms
on a Robinhood quote before acting. Yahoo can lag, so an event is a reason to look, never a trade by itself.

Each event fires once per level and day (private/state/monitor.json, local to this machine), so a target that's
been handled doesn't wake the session again; a raised stop is a new level and can fire.
"""

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import exits, paths, watches

ET = ZoneInfo("America/New_York")
FIRED = paths.STATE / "monitor.json"
OPEN, SAME_DAY_EXIT_AT, RECLAIM_BY = "09:30", "15:45", "15:30"  # ET; a reclaim bar must close by RECLAIM_BY
STALE_QUOTE_MIN = 10  # a quote older than this during regular hours counts as missing
FEED_DOWN_POLLS = 5  # consecutive polls with a symbol unpriced before the watcher gives up
VOLUME_BARS = 20  # a reclaim bar's volume must beat the average of the bars before it
PLAN_SIGNALS = ("STOP_HIT", "TARGET_HIT", "AT_1R")


def hhmm(t: datetime) -> str:
    return t.astimezone(ET).strftime("%H:%M")


def market_open(now: datetime, close: str = "16:00") -> bool:
    et = now.astimezone(ET)
    return et.weekday() < 5 and OPEN <= hhmm(et) < close


def quoted_symbol(plan: dict) -> str:
    return plan.get("underlying") or plan["symbol"]


def symbols(open_watches: list[dict], open_plans: list[dict]) -> list[str]:
    return sorted({w["symbol"] for w in open_watches} | {quoted_symbol(p) for p in open_plans})


def reclaim(w: dict, bars: list[dict], now: datetime) -> str | None:
    """CONFIRMED, INVALIDATED or None for a reclaim watch, from 15-minute bars (dicts with start, low, close,
    volume; start tz-aware). Only bars since the watch opened count, and only completed ones."""
    opened = datetime.fromisoformat(w["opened"])
    opened = opened.astimezone(ET) if opened.tzinfo is None else opened  # naive = this machine's local time
    done = [b for b in bars if b["start"] + timedelta(minutes=15) <= now]
    since = [b for b in done if b["start"] + timedelta(minutes=15) > opened]
    if not since:
        return None
    if min(b["low"] for b in since) <= w["stop"]:
        return "INVALIDATED"
    touch = next((i for i, b in enumerate(since) if b["low"] <= w["level"]), None)
    last = since[-1]
    before = done[-1 - VOLUME_BARS:-1]
    if touch is None or len(before) < VOLUME_BARS or hhmm(last["start"] + timedelta(minutes=15)) > RECLAIM_BY:
        return None
    avg = sum(b["volume"] for b in before) / len(before)
    return "CONFIRMED" if last["close"] > w["level"] and last["volume"] > avg else None


def events(open_watches: list[dict], open_plans: list[dict], prices: dict[str, float], now: datetime,
           bars=lambda symbol: []) -> list[dict]:
    """Every event for this poll (before de-duplication). bars(symbol) gives 15-minute bars for reclaim watches."""
    out = []
    for w in open_watches:
        px = prices.get(w["symbol"])
        if w.get("confirm") == "reclaim":
            state = reclaim(w, bars(w["symbol"]), now)
            if state is None and px is not None and px <= w["stop"]:
                state = "INVALIDATED"
            if state:
                out.append({"event": f"RECLAIM_{state}", "symbol": w["symbol"], "level": w["level"], "price": px,
                            "stop": w["stop"], "target": w.get("target"), "note": w["note"]})
        elif watches.evaluate(w, px, now.astimezone(ET).date()) == "TRIGGERED":
            out.append({"event": "WATCH_TRIGGERED", "symbol": w["symbol"], "level": w["level"], "price": px,
                        "note": w["note"]})
    for p in open_plans:
        px = prices.get(quoted_symbol(p))
        if px is not None:
            for sig in exits.evaluate(p, px, now.astimezone(ET).date()):
                if sig in PLAN_SIGNALS:
                    level = p["target"] if sig == "TARGET_HIT" else p["stop"]
                    out.append({"event": sig, "symbol": p["symbol"], "underlying": p.get("underlying"),
                                "level": level, "price": px})
        if p.get("thesis", "").startswith("[reclaim]") and hhmm(now) >= SAME_DAY_EXIT_AT:
            out.append({"event": "SAME_DAY_EXIT", "symbol": p["symbol"], "level": None, "price": px})
    return out


def key(e: dict, day: date) -> str:
    return f"{day.isoformat()}|{e['symbol']}|{e['event']}|{e['level']}"


def load_fired(path: Path) -> set[str]:
    return set(json.loads(path.read_text())) if path.exists() else set()


def save_fired(fired: set[str], day: date, path: Path) -> None:
    paths.ensure(path.parent)
    path.write_text(json.dumps(sorted(k for k in fired if k.startswith(day.isoformat()))))  # today's only


def yahoo_quotes(syms: list[str], now: datetime) -> dict[str, float]:
    """Last 1-minute close per symbol; a symbol with no bar in the last STALE_QUOTE_MIN minutes is left out."""
    import yfinance as yf

    from .market import yahoo_symbol

    out = {}
    for s in syms:
        try:
            h = yf.Ticker(yahoo_symbol(s)).history(period="1d", interval="1m")
            if len(h) and now - h.index[-1].to_pydatetime() <= timedelta(minutes=STALE_QUOTE_MIN):
                out[s] = round(float(h["Close"].iloc[-1]), 2)
        except Exception:
            pass
    return out


def yahoo_bars(symbol: str) -> list[dict]:
    import yfinance as yf

    from .market import yahoo_symbol

    try:
        h = yf.Ticker(yahoo_symbol(symbol)).history(period="5d", interval="15m")
    except Exception:
        return []
    return [{"start": t.to_pydatetime().astimezone(ET), "low": float(r.Low), "close": float(r.Close),
             "volume": float(r.Volume)} for t, r in h.iterrows()]


def run(minutes: float, interval: float = 60, close: str = "16:00", emit=print, now=lambda: datetime.now(ET),
        sleep=time.sleep, quotes=yahoo_quotes, bars=yahoo_bars, fired_path: Path = FIRED,
        watches_path: Path = watches.WATCHES, plans_path: Path = exits.PLANS) -> str:
    """Poll until an event, the heartbeat, the close or a dead feed. Returns the final state it printed."""
    start, misses = now(), {}
    while True:
        t = now()
        if not market_open(t, close):
            return final(emit, "CLOSED", t)
        ws = watches.open_watches(watches.load(watches_path))
        ws = [w for w in ws if t.astimezone(ET).date() <= date.fromisoformat(w["until"])]
        ps = exits.open_plans(exits.load(plans_path))
        syms = symbols(ws, ps)
        if not syms:
            return final(emit, "IDLE", t, note="no open watches or plans")
        prices = quotes(syms, t)
        for s in syms:
            misses[s] = 0 if s in prices else misses.get(s, 0) + 1
        dead = sorted(s for s, n in misses.items() if n >= FEED_DOWN_POLLS)
        if dead:
            return final(emit, "FEED_DOWN", t, symbols=dead,
                         note="no fresh Yahoo quote for 5 polls; fall back to 15-minute exit checks")
        day, fired = t.astimezone(ET).date(), load_fired(fired_path)
        new = [e for e in events(ws, ps, prices, t, bars) if key(e, day) not in fired]
        if new:
            for e in new:
                emit(json.dumps(e | {"time": hhmm(t), "source": "Yahoo (confirm on Robinhood)"}))
            save_fired(fired | {key(e, day) for e in new}, day, fired_path)
            return final(emit, "EVENT", t, count=len(new))
        if (t - start).total_seconds() >= minutes * 60:
            return final(emit, "HEARTBEAT", t, watching=syms)
        sleep(interval)


def final(emit, state: str, t: datetime, **extra) -> str:
    emit(json.dumps({"monitor": state, "time": hhmm(t)} | extra))
    return state
