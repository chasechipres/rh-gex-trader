"""Paper trading: a simulated account that takes the orders the playbook would send to Robinhood.

While private/state/paper.json is active, the hook refuses every real place_equity_order / place_option_order,
and orders go through `rhgex paper order` instead. Robinhood is still the data source: quotes come from
get_equity_quotes / get_option_quotes and are passed in as `--quote KEY=BID,ASK`.

The same guardrails apply as to a real order (blocked symbols, size and daily caps against the paper account's
value, an exit plan before an entry, the daily loss stop and the drawdown pause).

Fills, kept on the conservative side:
- market: buys at the ask, sells at the bid.
- limit, shares and funds: a buy fills at the ask once the ask is at or below the limit (a sell at the bid once
  the bid is at or above it); until then it rests.
- limit, options: a buy fills at min(limit, ask) once the limit is at or above the mid (liquid strikes fill at
  the mid); a sell at max(limit, bid) once the limit is at or below the mid.
- stop_market sell: triggers when the bid is at or below the stop, or a 15-minute bar's low since the last
  check touched it. It fills at the stop if price has come back above it, else at the bid (a gap fills worse).
- stop_limit sell: triggers the same way, then rests as a limit sell at its limit (it can get stuck, as on
  Robinhood).
A sell reserves the quantity, as Robinhood does: the resting stop must be cancelled before selling.
Positions are keyed by the stock symbol, or by the contract ("NVDA 2026-11-20 200C") for an option.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path

from . import dailyloss, exits, guardrails, paths

PAPER = paths.STATE / "paper.json"
CONTRACT_RE = re.compile(r"^([A-Z.]+) (\d{4}-\d{2}-\d{2}) (\d+(?:\.\d+)?)([CP])$")
TYPES = ("market", "limit", "stop_market", "stop_limit")


def active(path: Path | None = None) -> bool:
    path = path or PAPER
    return path.exists() and json.loads(path.read_text()).get("active", False)


def load(path: Path | None = None) -> dict:
    path = path or PAPER
    if not path.exists():
        raise ValueError("paper trading isn't started; run `rhgex paper start --cash 1500`")
    return json.loads(path.read_text())


def save(state: dict, path: Path | None = None) -> None:
    path = path or PAPER
    paths.ensure(path.parent)
    path.write_text(json.dumps(state, indent=2))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start(cash: float, path: Path | None = None, now: str | None = None) -> dict:
    path = path or PAPER
    if path.exists():
        raise ValueError(f"{path.name} already exists; paper trading started {load(path)['started']}")
    now = now or _now()
    state = {"active": True, "started": now, "starting_cash": cash, "cash": cash, "positions": {},
             "orders": [], "next_id": 1, "value": None}
    state["value"] = dailyloss.record(None, cash, now[:10], now)
    save(state, path)
    return state


def parse_key(key: str) -> dict:
    """A position key: a stock symbol, or an option contract "SYM YYYY-MM-DD STRIKE{C|P}"."""
    key = key.strip().upper()
    if m := CONTRACT_RE.match(key):
        return {"key": key, "symbol": m.group(1), "asset": "option", "mult": 100, "expiration": m.group(2),
                "strike": float(m.group(3)), "option_type": "call" if m.group(4) == "C" else "put"}
    if " " in key:
        raise ValueError(f"bad contract {key!r}; write it as 'NVDA 2026-11-20 200C'")
    return {"key": key, "symbol": key, "asset": "stock", "mult": 1}


def parse_quotes(items) -> dict[str, tuple[float, float]]:
    out = {}
    for item in items or []:
        k, _, v = item.rpartition("=")
        bid, ask = (float(x) for x in v.split(","))
        if bid > ask:
            raise ValueError(f"{k}: bid {bid} is above ask {ask}")
        out[k.strip().upper()] = (bid, ask)
    return out


def value(state: dict) -> float:
    return round(state["cash"] + sum(p["qty"] * p["mark"] * p["mult"] for p in state["positions"].values()), 2)


def _mark(state: dict, quotes: dict) -> None:
    for k, p in state["positions"].items():
        if k in quotes:
            bid, ask = quotes[k]
            p["mark"] = round((bid + ask) / 2, 4)


def _record_value(state: dict, now: str) -> None:
    state["value"] = dailyloss.record(state.get("value"), value(state), now[:10], now)


def _normalized(o: dict) -> dict:
    """The order as guardrails.check reads a real one."""
    k = parse_key(o["key"])
    px = o.get("limit")
    if k["asset"] == "stock":
        return {"symbol": k["symbol"], "asset": "stock", "side": o["side"], "type": o["type"], "quantity": o["qty"],
                "limit_price": px, "dollar_amount": None, "debit_or_credit": None, "legs": []}
    leg = {"option_type": k["option_type"], "strike": k["strike"], "expiration": k["expiration"], "side": o["side"],
           "position_effect": "open" if o["side"] == "buy" else "close", "ratio": 1}
    return {"symbol": k["symbol"], "asset": "option", "side": o["side"], "type": o["type"], "quantity": o["qty"],
            "limit_price": px, "dollar_amount": None, "debit_or_credit": "debit" if o["side"] == "buy" else "credit",
            "legs": [leg]}


def _ledger_today(state: dict, today: str) -> list[dict]:
    """Today's opening orders as the daily caps count them; a cancelled one counts only what filled."""
    rows = []
    for o in state["orders"]:
        if o["placed"][:10] != today or o["side"] != "buy":
            continue
        if o["state"] == "cancelled":
            continue
        rows.append({"opening": True, "cost_usd": o["qty"] * (o.get("fill_price") or o.get("limit") or 0)
                     * parse_key(o["key"])["mult"]})
    return rows


def _reserved(state: dict, key: str) -> float:
    return sum(o["qty"] for o in state["orders"] if o["key"] == key and o["side"] == "sell" and o["state"] == "open")


def _fill_price(o: dict, bid: float, ask: float, low: float | None = None) -> float | None:
    """The price this open order fills at against the quote (and the low since the last check), or None."""
    option = parse_key(o["key"])["asset"] == "option"
    mid = (bid + ask) / 2
    typ = o["type"]
    if typ in ("stop_market", "stop_limit") and not o.get("triggered"):
        if bid <= o["stop"] or (low is not None and low <= o["stop"]):
            o["triggered"] = _now()
        else:
            return None
        if typ == "stop_market":
            return o["stop"] if bid > o["stop"] else bid
    if typ == "market":
        return ask if o["side"] == "buy" else bid
    lim = o["limit"]
    if o["side"] == "buy":
        if option:
            return min(lim, ask) if lim >= mid else None
        return ask if ask <= lim else None
    if option:
        return max(lim, bid) if lim <= mid else None
    return bid if bid >= lim else None


def _apply_fill(state: dict, o: dict, px: float, now: str) -> dict:
    k = parse_key(o["key"])
    px = round(px, 4)
    o.update(state="filled", fill_price=px, filled=now)
    pos = state["positions"].get(k["key"])
    if o["side"] == "buy":
        if pos:
            qty = pos["qty"] + o["qty"]
            pos["avg_cost"] = round((pos["avg_cost"] * pos["qty"] + px * o["qty"]) / qty, 4)
            pos["qty"] = qty
        else:
            state["positions"][k["key"]] = {"symbol": k["symbol"], "asset": k["asset"], "mult": k["mult"],
                                            "qty": o["qty"], "avg_cost": px, "mark": px, "opened": now}
        state["cash"] = round(state["cash"] - px * o["qty"] * k["mult"], 2)
        return {"order": o["id"], "filled": o["key"], "side": "buy", "qty": o["qty"], "price": px}
    pnl = round((px - pos["avg_cost"]) * o["qty"] * k["mult"], 2)
    pnl_pct = round((px / pos["avg_cost"] - 1) * 100, 2)
    o.update(pnl=pnl, pnl_pct=pnl_pct)
    state["cash"] = round(state["cash"] + px * o["qty"] * k["mult"], 2)
    pos["qty"] -= o["qty"]
    pos["realized"] = round(pos.get("realized", 0) + pnl, 2)
    pos["cost_sold"] = round(pos.get("cost_sold", 0) + pos["avg_cost"] * o["qty"] * k["mult"], 2)
    res = {"order": o["id"], "filled": o["key"], "side": "sell", "qty": o["qty"], "price": px, "pnl": pnl,
           "pnl_pct": pnl_pct}
    if pos["qty"] <= 0:
        # The whole position's P/L for `journal exit --pnl --pnl-pct`, across partial sales.
        res["position_closed"] = {"pnl": pos["realized"],
                                  "pnl_pct": round(pos["realized"] / pos["cost_sold"] * 100, 2)}
        state.setdefault("closed", []).append({**pos, "key": k["key"], "closed": now})
        del state["positions"][k["key"]]
    return res


def order(key: str, side: str, qty: float, typ: str, limit: float | None = None, stop: float | None = None,
          quotes: dict | None = None, path: Path | None = None, cfg: dict | None = None, today: date | None = None,
          has_plan=exits.has_entry_plan, now: str | None = None) -> dict:
    """Place a paper order; fill it now if the quote allows, else it rests until `check`."""
    path = path or PAPER
    state, now = load(path), now or _now()
    today = today or date.today()
    k = parse_key(key)
    side, typ = side.lower(), typ.lower()
    if side not in ("buy", "sell") or typ not in TYPES:
        raise ValueError(f"side must be buy/sell and type one of {', '.join(TYPES)}")
    if qty <= 0 or (k["asset"] == "option" and qty != int(qty)):
        raise ValueError("quantity must be positive (whole contracts for options)")
    if typ in ("limit", "stop_limit") and limit is None:
        raise ValueError(f"a {typ} order needs --limit")
    if typ.startswith("stop") and (stop is None or side != "sell"):
        raise ValueError("stop orders are sells and need --stop")
    if side == "sell":
        held = state["positions"].get(k["key"], {}).get("qty", 0)
        free = held - _reserved(state, k["key"])
        if qty > free:
            raise ValueError(f"only {free:g} of {k['key']} free to sell ({held:g} held, the rest reserved by an "
                             "open sell order: cancel it first)")
    quotes = quotes or {}
    o = {"id": state["next_id"], "key": k["key"], "side": side, "qty": qty, "type": typ, "limit": limit, "stop": stop,
         "placed": now, "state": "open"}
    norm = _normalized(o)
    ok, reason = guardrails.check(cfg or guardrails.load(), norm, _ledger_today(state, now[:10]), today=today,
                                  account_value=value(state))
    if ok and side == "buy":
        if not has_plan(k["symbol"]):
            ok, reason = False, (f"no exit plan for {k['symbol']}; record one first with `rhgex plan add`")
        else:
            _mark(state, quotes)
            _record_value(state, now)
            lim = (cfg or guardrails.load())["limits"]
            ok, why = dailyloss.check(state["value"], now[:10],
                                      lim.get("max_daily_loss_pct", dailyloss.DEFAULT_PCT),
                                      lim.get("max_drawdown_pct", dailyloss.DEFAULT_DRAWDOWN_PCT))
            reason = reason if ok else why
    if ok and side == "buy" and typ == "market" and k["key"] in quotes:
        cost = quotes[k["key"]][1] * qty * k["mult"]
        if cost > state["cash"]:
            ok, reason = False, f"not enough paper cash: ${cost:,.2f} needed, ${state['cash']:,.2f} free"
    if ok and side == "buy" and limit is not None and limit * qty * k["mult"] > state["cash"]:
        ok, reason = False, f"not enough paper cash: ${limit * qty * k['mult']:,.2f} needed, ${state['cash']:,.2f} free"
    if not ok:
        return {"refused": reason}
    if typ == "market" and k["key"] not in quotes:
        raise ValueError(f"a market order needs --quote {k['key']}=BID,ASK")
    state["next_id"] += 1
    state["orders"].append(o)
    res = {"placed": o, "guardrails": reason}
    if k["key"] in quotes:
        px = _fill_price(o, *quotes[k["key"]])
        if px is not None:
            res["fill"] = _apply_fill(state, o, px, now)
    _mark(state, quotes)
    _record_value(state, now)
    save(state, path)
    return res


def cancel(target: str, path: Path | None = None, now: str | None = None) -> dict:
    """Cancel an open order by id, or every open order for a key (symbol or contract)."""
    path = path or PAPER
    state = load(path)
    hit = [o for o in state["orders"] if o["state"] == "open"
           and (str(o["id"]) == target or o["key"] == target.strip().upper())]
    if not hit:
        raise ValueError(f"no open paper order matches {target!r}")
    for o in hit:
        o.update(state="cancelled", cancelled=now or _now())
    save(state, path)
    return {"cancelled": [o["id"] for o in hit]}


def check(quotes: dict, path: Path | None = None, lows=None, now: str | None = None) -> dict:
    """Run open orders against the quotes (and, for stops, each stock's 15-minute lows since the last check)."""
    path = path or PAPER
    state, now = load(path), now or _now()
    since = state.get("checked") or state["started"]
    fills, stuck = [], []
    for o in [o for o in state["orders"] if o["state"] == "open"]:
        if o["key"] not in quotes:
            continue
        low = None
        if lows and o["type"].startswith("stop") and parse_key(o["key"])["asset"] == "stock":
            low = lows(o["key"], max(since, o["placed"]))
        px = _fill_price(o, *quotes[o["key"]], low=low)
        if px is not None:
            fills.append(_apply_fill(state, o, px, now))
        elif o.get("triggered"):
            stuck.append(o["id"])
    _mark(state, quotes)
    _record_value(state, now)
    state["checked"] = now
    save(state, path)
    missing = sorted({o["key"] for o in state["orders"] if o["state"] == "open"} - set(quotes))
    return {"fills": fills, "stuck_stops": stuck, "no_quote": missing, **summary(state)}


def summary(state: dict) -> dict:
    v = value(state)
    start_cash = state["starting_cash"]
    return {"started": state["started"], "starting_cash": start_cash, "cash": state["cash"], "value": v,
            "return_pct": round((v / start_cash - 1) * 100, 2),
            "positions": {k: {"qty": p["qty"], "avg_cost": p["avg_cost"], "mark": p["mark"],
                              "unrealized": round((p["mark"] - p["avg_cost"]) * p["qty"] * p["mult"], 2)}
                          for k, p in state["positions"].items()},
            "open_orders": [o for o in state["orders"] if o["state"] == "open"],
            "day": {"start_value": state["value"]["start_value"], "peak_value": state["value"]["peak_value"]}}


def status(quotes: dict | None = None, path: Path | None = None, now: str | None = None) -> dict:
    path = path or PAPER
    state, now = load(path), now or _now()
    if quotes:
        _mark(state, quotes)
        _record_value(state, now)
        save(state, path)
    return summary(state)


def yahoo_lows(symbol: str, since: str) -> float | None:
    """The lowest 15-minute low from `since` (local ISO time) to now, from Yahoo; None if unavailable."""
    from .monitor import yahoo_bars

    t0 = datetime.fromisoformat(since).astimezone()
    lows = [b["low"] for b in yahoo_bars(symbol) if b["start"] >= t0.replace(second=0)]
    return min(lows) if lows else None
