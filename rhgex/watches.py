"""Watch triggers (private/state/watches.json): the price that turns a journaled `watch` into a candidate.

A cycle that journals a `watch` also adds its trigger here; every exit check prices the open watches and
reports the ones that fired, so a trigger between the three daily cycles isn't missed. A trigger is a level
on the underlying (`above` or `below`) and lapses after `until` (default: 2 trading days, the fresh-post window).
With a stop and a target, a watch is refused unless the trade clears the minimum reward:risk from the trigger
price, so a trigger that fires is already worth researching.

A reclaim watch (`--reclaim`) is for buying back above one of his dip levels: `rhgex monitor` fires it only on a
completed 15-minute close above the level on above-average volume after price touched it, and drops it if price
trades through the stop first. `watch check` (Robinhood prices, no bars) still reports it TRIGGERED on price, with
`confirm: reclaim`, so the exit check knows to look at the 15-minute bars before entering.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import exits, paths

WATCHES = paths.STATE / "watches.json"
DEFAULT_DAYS = 2  # trading days a trigger stays live, like the fresh-post rule


def load(path: Path = WATCHES) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def save(watches: list[dict], path: Path = WATCHES) -> None:
    paths.ensure(path.parent)
    path.write_text(json.dumps(watches, indent=2))


def open_watches(watches: list[dict]) -> list[dict]:
    return [w for w in watches if w["status"] == "open"]


def add_trading_days(day: date, n: int) -> date:
    while n > 0:
        day += timedelta(days=1)
        n -= day.weekday() < 5
    return day


def add(symbol: str, side: str, level: float, note: str, until: str | None = None, source: str = "",
        today: date | None = None, path: Path = WATCHES, stop: float | None = None,
        target: float | None = None, reclaim: bool = False) -> dict:
    """side: 'above' fires when price >= level, 'below' when price <= level. One open watch per symbol.
    stop/target (on the underlying, both or neither): the trade must clear exits.MIN_REWARD_RISK from the trigger.
    reclaim: his level is `level`, the stop is his invalidation; needs side 'above' and a stop."""
    if side not in ("above", "below"):
        raise ValueError("side must be above or below")
    if reclaim and (side != "above" or stop is None):
        raise ValueError("a reclaim watch needs --above his level and --stop his invalidation")
    rr = None
    if (stop is None) != (target is None):
        raise ValueError("pass both --stop and --target, or neither")
    if stop is not None:
        direction = "bullish" if target > level else "bearish"
        rr = exits.reward_risk(direction, level, stop, target)  # raises if the trigger isn't between them
        if rr < exits.MIN_REWARD_RISK:
            raise ValueError(f"reward:risk {rr} from the trigger {level} is below {exits.MIN_REWARD_RISK}; "
                             "move the trigger closer to his level or skip it")
    today = today or date.today()
    end = date.fromisoformat(until) if until else add_trading_days(today, DEFAULT_DAYS)
    if end < today:
        raise ValueError(f"until {end} is in the past")
    watches = load(path)
    symbol = symbol.upper()
    for w in open_watches(watches):  # a new trigger replaces the old one
        if w["symbol"] == symbol:
            w.update(status="replaced", closed=datetime.now().isoformat(timespec="seconds"))
    w = {"symbol": symbol, "side": side, "level": level, "until": end.isoformat(), "note": note, "source": source,
         "status": "open", "opened": datetime.now().isoformat(timespec="seconds")}
    if rr is not None:
        w.update(stop=stop, target=target, reward_risk=rr)
    if reclaim:
        w["confirm"] = "reclaim"
    watches.append(w)
    save(watches, path)
    return w


def close(symbol: str, reason: str, path: Path = WATCHES) -> dict:
    watches = load(path)
    for w in open_watches(watches):
        if w["symbol"] == symbol.upper():
            w.update(status="closed", closed=datetime.now().isoformat(timespec="seconds"), close_reason=reason)
            save(watches, path)
            return w
    raise ValueError(f"no open watch for {symbol.upper()}")


def evaluate(w: dict, price: float | None, today: date) -> str:
    if today > date.fromisoformat(w["until"]):
        return "EXPIRED"
    if price is None:
        return "NO_PRICE"
    hit = price >= w["level"] if w["side"] == "above" else price <= w["level"]
    return "TRIGGERED" if hit else "WAITING"


def check(prices: dict[str, float], today: date | None = None, path: Path = WATCHES) -> list[dict]:
    """Every open watch against prices. Expired ones are closed here, so the list only shrinks on its own."""
    today = today or date.today()
    prices = {k.upper(): v for k, v in prices.items()}
    watches = load(path)
    report = []
    for w in open_watches(watches):
        px = prices.get(w["symbol"])
        state = evaluate(w, px, today)
        if state == "EXPIRED":
            w.update(status="expired", closed=datetime.now().isoformat(timespec="seconds"))
        report.append({"symbol": w["symbol"], "trigger": f"{w['side']} {w['level']:g}", "price": px,
                       "until": w["until"], "state": state, "note": w["note"]}
                      | ({"confirm": "reclaim", "stop": w["stop"]} if w.get("confirm") == "reclaim" else {}))
    if any(r["state"] == "EXPIRED" for r in report):
        save(watches, path)
    return report
