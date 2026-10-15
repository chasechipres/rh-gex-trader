"""Hard limits for Robinhood orders. Pure functions over a normalized order; the hook supplies the order.

Normalized order:
    {"symbol": "NVDA", "asset": "stock" | "option", "side": "buy" | "sell",
     "quantity": 2, "limit_price": 101.5 | None, "dollar_amount": None | 250.0,
     "debit_or_credit": "debit" | "credit" | None,          # multi-leg net price direction
     "legs": [{"option_type": "call" | "put", "strike": 110.0, "expiration": "2026-11-20",
               "side": "buy" | "sell", "position_effect": "open" | "close" | None, "ratio": 1}]}
"""

import tomllib
from datetime import date
from pathlib import Path

from . import leveraged, paths

CONFIG = paths.GUARDRAILS
CONTRACT = 100


def load(path: Path = CONFIG) -> dict:
    if not path.exists():  # a fresh clone: every order is refused until the owner writes their limits
        raise FileNotFoundError(f"{path} is missing; set up private/ with `uv run python -m rhgex init` (see README)")
    with open(path, "rb") as f:
        return tomllib.load(f)


def active_blocks(cfg: dict, today: date) -> dict[str, str]:
    """symbol -> block name, for blocks that haven't expired."""
    out = {}
    for b in cfg.get("blocked", []):
        if not b.get("until") or today <= date.fromisoformat(b["until"]):
            out.update({s.upper(): b["name"] for s in b["symbols"]})
    return out


def is_opening(order: dict) -> bool:
    if order["asset"] == "stock":
        return order["side"] == "buy"
    return any(leg.get("position_effect") != "close" for leg in order["legs"])


def cost(order: dict) -> float:
    """Max loss / capital committed by an opening order. Raises ValueError when it can't be bounded."""
    qty, px = order.get("quantity"), order.get("limit_price")
    if order["asset"] == "stock":
        if order.get("dollar_amount"):
            return float(order["dollar_amount"])
        if not (qty and px):
            raise ValueError("stock order needs a quantity and a limit price (or a dollar amount)")
        return qty * px

    legs = order["legs"]
    if not (qty and px):
        raise ValueError("option order needs a quantity and a limit price")
    if len(legs) == 1:
        if legs[0]["side"] != "buy":
            raise ValueError("selling to open a single option is undefined risk; only buy-to-open is allowed")
        return qty * px * CONTRACT
    if len(legs) == 2:
        a, b = legs
        if not (a["option_type"] == b["option_type"] and a["expiration"] == b["expiration"]
                and {a["side"], b["side"]} == {"buy", "sell"} and a.get("ratio", 1) == b.get("ratio", 1)):
            raise ValueError("only same-expiry 1:1 vertical spreads are allowed as multi-leg orders")
        if order.get("debit_or_credit") == "debit":
            return qty * px * CONTRACT
        if order.get("debit_or_credit") == "credit":
            width = abs(a["strike"] - b["strike"])
            return qty * (width - px) * CONTRACT
        raise ValueError("spread order must say whether its price is a debit or a credit")
    raise ValueError("orders with more than 2 legs are not allowed")


def limit(lim: dict, name: str, account_value: float | None) -> float:
    """Dollar limit for max_<name>: <name>_pct of the account value (capped by max_<name>_usd if also set),
    or max_<name>_usd alone. Raises ValueError when a percentage applies but the account value is unknown."""
    pct, usd = lim.get(f"max_{name}_pct"), lim.get(f"max_{name}_usd")
    if pct is None:
        if usd is None:
            raise ValueError(f"guardrails.toml sets neither max_{name}_pct nor max_{name}_usd")
        return float(usd)
    if not account_value:
        raise ValueError("account value unknown today; call get_portfolio for this account first")
    cap = round(pct / 100 * account_value, 2)
    return min(cap, float(usd)) if usd is not None else cap


def check(cfg: dict, order: dict, ledger_today: list[dict], today: date | None = None,
          account_value: float | None = None) -> tuple[bool, str]:
    today = today or date.today()
    lim = cfg["limits"]
    symbol = (order.get("symbol") or "").upper()
    if not symbol:
        return False, "could not determine the symbol"

    # Blocked symbols are off-limits both ways: no new positions, and no selling the user's own holdings.
    blocks = active_blocks(cfg, today)
    if symbol in blocks:
        return False, f"{symbol} is blocked ({blocks[symbol]})"
    fund = leveraged.underlying(symbol)
    if fund and fund[0] in blocks:  # a leveraged fund on a blocked stock is the same exposure
        return False, f"{symbol} is a {fund[1]}x fund on {fund[0]}, which is blocked ({blocks[fund[0]]})"

    if not is_opening(order):
        # Robinhood cash/agentic accounts can't short stock, so a stock sell is an exit.
        return True, "exit order: always allowed"

    if lim.get("require_limit_orders") and not order.get("limit_price") and not (
            order["asset"] == "stock" and order.get("dollar_amount")):
        return False, "opening orders must be limit orders"

    try:
        c = cost(order)
    except ValueError as e:
        return False, str(e)
    if c <= 0:
        return False, f"could not bound the order's risk (computed {c})"
    try:
        caps = {n: limit(lim, n, account_value) for n in ("order", "option_premium", "daily_deployed")}
    except ValueError as e:
        return False, str(e)

    if order["asset"] == "stock":
        if c > caps["order"]:
            return False, f"order ${c:.2f} exceeds the stock order limit ${caps['order']:.2f}"
    else:
        if c > caps["option_premium"]:
            return False, f"option max loss ${c:.2f} exceeds the option limit ${caps['option_premium']:.2f}"
        for leg in order["legs"]:
            dte = (date.fromisoformat(leg["expiration"]) - today).days
            if dte < lim["min_option_dte"]:
                return False, f"expiry {leg['expiration']} is {dte} days out; minimum is {lim['min_option_dte']}"

    opens = [e for e in ledger_today if e.get("opening")]
    if len(opens) >= lim["max_new_positions_per_day"]:
        return False, f"already opened {len(opens)} positions today (max {lim['max_new_positions_per_day']})"
    deployed = sum(e.get("cost_usd", 0) for e in opens)
    if deployed + c > caps["daily_deployed"]:
        return False, f"would deploy ${deployed + c:.2f} today (max ${caps['daily_deployed']:.2f})"

    return True, f"ok: opening cost ${c:.2f}"
