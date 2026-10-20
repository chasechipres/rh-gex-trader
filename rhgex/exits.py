"""Structured exit plans (private/state/plans.json) and the exit check run at the start of every cycle.

A plan is written before entry with `rhgex plan add` and closed after the exit with `rhgex plan close`.
Stops and targets are levels on the UNDERLYING, with a direction: bullish positions (shares, long calls,
call debit spreads) stop out below and take profit above; bearish ones (long puts, put debit spreads) the
reverse. The hook refuses opening orders for symbols without an open plan.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import leveraged, paths

PLANS = paths.STATE / "plans.json"
EXPIRY_EXIT_DAYS = 2  # close options this many days or fewer before expiry unless the thesis is playing out
MIN_REWARD_RISK = 1.5  # |target - price| / |price - stop| on the underlying, required for a new entry
EARNINGS_EXIT_DAYS = 3  # flag holdings whose earnings report is this many trading days away or fewer
SHARE_TIME_STOP_DAYS = 10  # shares that haven't reached 1R (stop still below breakeven) after this many trading days


def load(path: Path = PLANS) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def save(plans: list[dict], path: Path = PLANS) -> None:
    paths.ensure(path.parent)
    path.write_text(json.dumps(plans, indent=2))


def open_plans(plans: list[dict]) -> list[dict]:
    return [p for p in plans if p["status"] == "open"]


def has_open_plan(symbol: str, path: Path = PLANS) -> bool:
    return any(p["symbol"] == symbol.upper() for p in open_plans(load(path)))


def has_entry_plan(symbol: str, path: Path = PLANS) -> bool:
    """An open plan that allows a new entry: not one rebuilt with --existing for a position already held."""
    return any(p["symbol"] == symbol.upper() and not p.get("existing") for p in open_plans(load(path)))


def reward_risk(direction: str, price: float, stop: float, target: float) -> float:
    bull = direction == "bullish"
    if (bull and not stop < price < target) or (not bull and not target < price < stop):
        raise ValueError(f"price {price} must be between the stop {stop} and the target {target}")
    return round(abs(target - price) / abs(price - stop), 2)


def entry_cap(direction: str, stop: float, target: float) -> float:
    """The worst underlying price a new entry can take and still have MIN_REWARD_RISK: the highest for a bullish
    entry, the lowest for a bearish one. A breakout's marketable limit never goes past it."""
    return round((target + MIN_REWARD_RISK * stop) / (1 + MIN_REWARD_RISK), 2)


def add(symbol: str, asset: str, direction: str, stop: float, target: float, thesis: str,
        expiration: str | None = None, premium_stop: float | None = None, path: Path = PLANS,
        price: float | None = None, existing: bool = False) -> dict:
    """price is the underlying's current price: a new entry needs reward:risk >= MIN_REWARD_RISK from it.
    existing=True rebuilds the plan for a position already held and skips that check."""
    symbol = symbol.upper()
    if direction not in ("bullish", "bearish"):
        raise ValueError("direction must be bullish or bearish")
    if (direction == "bullish" and not stop < target) or (direction == "bearish" and not stop > target):
        raise ValueError(f"{direction} plan needs stop {'below' if direction == 'bullish' else 'above'} target")
    if asset == "option":
        if not expiration:
            raise ValueError("option plans need --expiration")
        date.fromisoformat(expiration)
    elif asset != "stock":
        raise ValueError("asset must be stock or option")
    rr = None
    if not existing:
        if price is None:
            raise ValueError("a new plan needs the underlying's current price (--price)")
        rr = reward_risk(direction, price, stop, target)
        if rr < MIN_REWARD_RISK:
            raise ValueError(f"reward:risk {rr} from {price} is below {MIN_REWARD_RISK}")
    plans = load(path)
    if any(p["symbol"] == symbol for p in open_plans(plans)):
        raise ValueError(f"{symbol} already has an open plan; close it first")
    plan = {"symbol": symbol, "asset": asset, "direction": direction, "stop": stop, "target": target,
            "expiration": expiration, "premium_stop": premium_stop, "price": price, "reward_risk": rr,
            "existing": existing, "thesis": thesis, "status": "open",
            "opened": datetime.now().isoformat(timespec="seconds")}
    fund = leveraged.underlying(symbol) if asset == "stock" else None
    if fund:  # levels and price are the underlying's; the exit check quotes it
        plan.update(underlying=fund[0], leverage=fund[1])
    plans.append(plan)
    save(plans, path)
    return plan


def close(symbol: str, reason: str, path: Path = PLANS) -> dict:
    plans = load(path)
    for p in open_plans(plans):
        if p["symbol"] == symbol.upper():
            p.update(status="closed", closed=datetime.now().isoformat(timespec="seconds"), close_reason=reason)
            save(plans, path)
            return p
    raise ValueError(f"no open plan for {symbol.upper()}")


def raise_stop(symbol: str, stop: float, path: Path = PLANS) -> dict:
    """Tighten an open plan's underlying stop (up for bullish, down for bearish). Never loosens it."""
    plans = load(path)
    for p in open_plans(plans):
        if p["symbol"] == symbol.upper():
            bull = p["direction"] == "bullish"
            if (bull and stop <= p["stop"]) or (not bull and stop >= p["stop"]):
                raise ValueError(f"new stop {stop} doesn't tighten the current {p['stop']}; stops only move "
                                 f"{'up' if bull else 'down'}")
            p.setdefault("initial_stop", p["stop"])
            p["stop"] = stop
            save(plans, path)
            return p
    raise ValueError(f"no open plan for {symbol.upper()}")


def at_one_r(plan: dict, price: float) -> bool:
    """1R in profit from the plan's entry while the stop is still below breakeven: time to raise it."""
    entry = plan.get("price")
    stop = plan.get("initial_stop", plan["stop"])
    if entry is None:
        return False
    bull = plan["direction"] == "bullish"
    risk = abs(entry - stop)
    at_breakeven = plan["stop"] >= entry if bull else plan["stop"] <= entry
    return not at_breakeven and (price >= entry + risk if bull else price <= entry - risk)


def trading_days_until(day: date, today: date) -> int:
    """Weekdays from today (exclusive) through day (inclusive); holidays aren't counted out."""
    return sum(1 for n in range(1, (day - today).days + 1) if (today + timedelta(days=n)).weekday() < 5)


def evaluate(plan: dict, price: float | None, today: date, earnings: date | None = None) -> list[str]:
    """Signals for one plan: STOP_HIT, TARGET_HIT, AT_1R, EXPIRING, EARNINGS_SOON, TIME_STOP, NO_PRICE.
    Empty means hold."""
    out = []
    if price is None:
        out.append("NO_PRICE")
    else:
        bull = plan["direction"] == "bullish"
        if (bull and price <= plan["stop"]) or (not bull and price >= plan["stop"]):
            out.append("STOP_HIT")
        elif (bull and price >= plan["target"]) or (not bull and price <= plan["target"]):
            out.append("TARGET_HIT")
        elif at_one_r(plan, price):
            out.append("AT_1R")
    if plan["asset"] == "option" and (date.fromisoformat(plan["expiration"]) - today).days <= EXPIRY_EXIT_DAYS:
        out.append("EXPIRING")
    if earnings is not None and today <= earnings and trading_days_until(earnings, today) <= EARNINGS_EXIT_DAYS:
        out.append("EARNINGS_SOON")
    if time_stop(plan, today):
        out.append("TIME_STOP")
    return out


def time_stop(plan: dict, today: date) -> bool:
    """Shares held SHARE_TIME_STOP_DAYS trading days without reaching 1R (the stop never moved to breakeven)."""
    if plan["asset"] != "stock" or plan.get("price") is None or not plan.get("opened"):
        return False
    entry, bull = plan["price"], plan["direction"] == "bullish"
    at_breakeven = plan["stop"] >= entry if bull else plan["stop"] <= entry
    opened = date.fromisoformat(plan["opened"][:10])
    days = leveraged.TIME_STOP_DAYS if plan.get("leverage") else SHARE_TIME_STOP_DAYS
    return not at_breakeven and trading_days_until(today, opened) >= days


def last_price(symbol: str) -> float | None:
    from .market import yahoo_symbol
    import yfinance as yf

    try:
        h = yf.Ticker(yahoo_symbol(symbol)).history(period="1d", interval="1m")
        return round(float(h["Close"].iloc[-1]), 2) if len(h) else None
    except Exception:
        return None


def earnings_date(symbol: str) -> date | None:
    from .market import next_earnings

    return next_earnings(symbol)


def check(prices: dict[str, float] | None = None, today: date | None = None, path: Path = PLANS,
          earnings=earnings_date) -> list[dict]:
    today = today or date.today()
    prices = {k.upper(): v for k, v in (prices or {}).items()}
    report = []
    for p in open_plans(load(path)):
        quoted = p.get("underlying") or p["symbol"]  # a leveraged fund's levels are on its stock
        passed = prices.get(quoted)
        px = passed or last_price(quoted)
        er = earnings(quoted)
        report.append({"symbol": p["symbol"], "underlying": p.get("underlying"), "asset": p["asset"],
                       "direction": p["direction"], "price": px,
                       "price_source": "passed" if passed else f"Yahoo (may lag; pass --price {quoted}=PX)",
                       "stop": p["stop"], "target": p["target"], "expiration": p["expiration"],
                       "earnings": er.isoformat() if er else None,
                       "signals": evaluate(p, px, today, er) or ["HOLD"]})
        fund_px = prices.get(p["symbol"]) if p.get("underlying") else None
        if fund_px and passed:  # where the fund's resting stop belongs for the plan's current stop on the stock
            report[-1]["fund_stop"] = leveraged.fund_level(fund_px, passed, p["stop"], p["leverage"])
    return report
