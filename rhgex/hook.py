"""Claude Code hooks for the Robinhood MCP server (robinhood-trading).

pre:  PreToolUse. Read/preview tools, cancels and watchlist/alert/scan tools pass. place_equity_order and
      place_option_order are normalized and run through guardrails.check. Everything else is denied or sent
      to the user (fail closed): an unknown tool, an unparseable order, or a crashing hook never gets through.
post: PostToolUse. Records placed orders in private/state/ledger.jsonl, which the daily limits read, and each
      account's value from get_portfolio in private/state/account.json, which the percentage limits read.
      When get_equity_orders / get_option_orders shows one of today's opening orders cancelled (or rejected)
      unfilled, it appends a release row, so the daily caps stop counting money that was never spent.
"""

import json
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

from . import dailyloss, exits, guardrails, paths

LEDGER = paths.STATE / "ledger.jsonl"
ACCOUNT = paths.STATE / "account.json"
INSTRUMENT_URL = "https://api.robinhood.com/options/instruments/{}/"

ORDER_TOOLS = {"place_equity_order", "place_option_order"}
READ_PREFIXES = ("get_", "search", "review_", "preview_")
HARMLESS = {
    "add_to_watchlist", "remove_from_watchlist", "add_option_to_watchlist", "remove_option_from_watchlist",
    "create_watchlist", "update_watchlist", "follow_watchlist", "unfollow_watchlist",
    "create_alert", "update_alert", "delete_alert", "mark_alerts_read",
    "create_scan", "update_scan_config", "update_scan_filters", "run_scan",
    "add_legend_indicator", "update_legend_indicator", "remove_legend_indicator", "set_legend_chart_settings",
}
ASK = {"exercise_option": "exercising an option moves real cash or shares; the user approves each one"}
DENY = {"place_crypto_order": "crypto is out of scope for this agent"}


def classify(tool_name: str) -> str:
    name = tool_name.rsplit("__", 1)[-1].lower()
    if name in ORDER_TOOLS:
        return "order"
    if name in DENY:
        return "deny"
    if name in ASK:
        return "ask"
    if name.startswith("cancel_"):
        return "cancel"
    if name.startswith(READ_PREFIXES):
        return "read"
    if name in HARMLESS:
        return "harmless"
    return "unknown"


def _num(v):
    return float(v) if v not in (None, "") else None


def instrument(option_id: str) -> dict:
    """Resolve an option_id via Robinhood's public instrument endpoint."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", option_id or ""):
        raise ValueError(f"bad option_id {option_id!r}")
    req = urllib.request.Request(INSTRUMENT_URL.format(option_id), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def underlying(chain_symbol: str) -> str:
    # Adjusted chains get a digit suffix (XYZ1); weekly SPX is SPXW.
    s = re.sub(r"\d+$", "", chain_symbol.upper())
    return "SPX" if s == "SPXW" else s


def normalize(tool: str, d: dict, lookup=instrument) -> dict:
    """Map place_equity_order / place_option_order arguments onto guardrails' normalized order."""
    name = tool.rsplit("__", 1)[-1]
    if name == "place_equity_order":
        side = str(d.get("side", "")).lower()
        if side not in ("buy", "sell") or not d.get("symbol"):
            raise ValueError("equity order needs symbol and side buy/sell")
        typ = str(d.get("type", "")).lower()
        return {"symbol": d["symbol"].upper(), "asset": "stock", "side": side, "type": typ,
                "quantity": _num(d.get("quantity")),
                "limit_price": _num(d.get("limit_price")) if typ in ("limit", "stop_limit") else None,
                "dollar_amount": _num(d.get("dollar_amount")), "debit_or_credit": None, "legs": []}

    if name == "place_option_order":
        legs_in = d.get("legs") or []
        if not legs_in:
            raise ValueError("option order has no legs")
        legs, symbols = [], set()
        for x in legs_in:
            inst = lookup(x.get("option_id", ""))
            symbols.add(underlying(inst["chain_symbol"]))
            side, effect = str(x.get("side", "")).lower(), str(x.get("position_effect", "")).lower()
            if side not in ("buy", "sell") or effect not in ("open", "close"):
                raise ValueError(f"leg needs side buy/sell and position_effect open/close: {x}")
            legs.append({"option_type": inst["type"], "strike": float(inst["strike_price"]),
                         "expiration": inst["expiration_date"], "side": side, "position_effect": effect,
                         "ratio": int(x.get("ratio_quantity") or 1)})
        if len(symbols) != 1:
            raise ValueError(f"legs span several underlyings: {symbols}")
        typ = str(d.get("type") or "limit").lower()
        direction = str(d.get("direction") or "").lower() or None
        if len(legs) == 1:
            direction = "debit" if legs[0]["side"] == "buy" else "credit"
        return {"symbol": symbols.pop(), "asset": "option", "side": legs[0]["side"], "type": typ,
                "quantity": _num(d.get("quantity")),
                "limit_price": _num(d.get("price")) if typ in ("limit", "stop_limit") else None,
                "dollar_amount": None, "debit_or_credit": direction, "legs": legs}

    raise ValueError(f"{name} is not an order tool")


def _rows_today() -> list[dict]:
    if not LEDGER.exists():
        return []
    today = date.today().isoformat()
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("date") == today]


def settle(rows: list[dict]) -> list[dict]:
    """Apply release rows: an opening order the broker finished unfilled drops out; a partial fill counts at
    its filled fraction of the cost."""
    filled = {r["order_id"]: r["filled_fraction"] for r in rows if r.get("tool") == "release"}
    out = []
    for r in rows:
        if r.get("tool") == "release":
            continue
        f = filled.get(r.get("order_id")) if r.get("order_id") else None
        if f is None:
            out.append(r)
        elif f > 0:
            out.append({**r, "cost_usd": round(r.get("cost_usd", 0) * f, 2)})
    return out


def ledger_today() -> list[dict]:
    """Today's orders as the daily caps count them: placed orders, less what the broker says never filled."""
    return settle(_rows_today())


# Final states with nothing (or only part) filled: the unfilled rest never cost anything.
UNFILLED_FINAL = {"cancelled", "rejected", "failed", "voided", "partially_filled_rest_cancelled"}


def releases(resp, rows: list[dict]) -> list[dict]:
    """Release rows for today's opening orders that an orders listing shows finished unfilled or part-filled.
    Only the broker's own order states release cap: a cancel request alone doesn't, since a fill can race it."""
    data = (_payload(resp) or {}).get("data")
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        return []
    opened = {r["order_id"] for r in rows if r.get("opening") and r.get("order_id") and r.get("tool") != "release"}
    done = {r.get("order_id") for r in rows if r.get("tool") == "release"}
    out = []
    for o in orders:
        if not isinstance(o, dict) or o.get("state") not in UNFILLED_FINAL:
            continue
        oid = str(o.get("id") or "")
        qty = _num(o.get("quantity"))
        got = _num(o.get("cumulative_quantity", o.get("processed_quantity")))
        if oid not in opened or oid in done or not qty or got is None:
            continue
        out.append({"time": datetime.now().isoformat(timespec="seconds"), "date": date.today().isoformat(),
                    "tool": "release", "order_id": oid, "state": o["state"], "opening": False, "cost_usd": 0,
                    "filled_fraction": round(min(got / qty, 1.0), 6)})
        done.add(oid)
    return out


def _payload(resp):
    """The JSON object in an MCP tool response: a JSON string, a list of text blocks, or a dict."""
    if isinstance(resp, str):
        try:
            return _payload(json.loads(resp))
        except ValueError:
            return None
    if isinstance(resp, list):
        for x in resp:
            p = _payload(x.get("text") if isinstance(x, dict) and "text" in x else x)
            if p is not None:
                return p
        return None
    if isinstance(resp, dict):
        return _payload(resp["content"]) if "content" in resp and "data" not in resp else resp
    return None


def order_id(resp) -> str | None:
    """The placed order's id from the tool response, if there is one."""
    data = (_payload(resp) or {}).get("data")
    if not isinstance(data, dict):
        return None
    o = data.get("order") if isinstance(data.get("order"), dict) else data
    return str(o["id"]) if o.get("id") else None


def record_portfolio(args: dict, resp) -> None:
    acct = str(args.get("account_number") or "")
    data = (_payload(resp) or {}).get("data") or {}
    value = _num(data.get("total_value"))
    if not acct or not value or not paths.ready(ACCOUNT):
        return  # (no private/ yet: nowhere to record before `rhgex init`)
    accounts = json.loads(ACCOUNT.read_text()) if ACCOUNT.exists() else {}
    accounts[acct] = dailyloss.record(accounts.get(acct), value, date.today().isoformat(),
                                      datetime.now().isoformat(timespec="seconds"))
    paths.ensure(ACCOUNT.parent)
    ACCOUNT.write_text(json.dumps(accounts, indent=2))


def account_value(account_number) -> float | None:
    """The account's value recorded today, or None (an older value doesn't count)."""
    if not ACCOUNT.exists():
        return None
    rec = json.loads(ACCOUNT.read_text()).get(str(account_number or ""))
    return rec["total_value"] if rec and rec.get("date") == date.today().isoformat() else None


def account_record(account_number) -> dict | None:
    if not ACCOUNT.exists():
        return None
    return json.loads(ACCOUNT.read_text()).get(str(account_number or ""))


def _decide(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision,
        "permissionDecisionReason": f"rhgex guardrails: {reason}"}}))


def pre(event: dict) -> None:
    tool, args = event.get("tool_name", ""), event.get("tool_input") or {}
    name = tool.rsplit("__", 1)[-1]
    kind = classify(tool)
    if kind in ("read", "cancel", "harmless"):
        return _decide("allow", f"{kind} tool")
    if kind == "deny":
        return _decide("deny", DENY[name])
    if kind == "ask":
        return _decide("ask", ASK[name])
    if kind == "unknown":
        return _decide("deny", f"unrecognized Robinhood tool {tool}; map it in rhgex/hook.py first")
    try:
        order = normalize(tool, args)
    except Exception as e:
        return _decide("deny", f"could not parse order ({type(e).__name__}: {e}); refusing")
    cfg = guardrails.load()
    ok, reason = guardrails.check(cfg, order, ledger_today(),
                                  account_value=account_value(args.get("account_number")))
    if ok and guardrails.is_opening(order) and not exits.has_entry_plan(order["symbol"]):
        ok, reason = False, (f"no exit plan for {order['symbol']}; record one first with `rhgex plan add` "
                             "(a plan added with --existing covers a held position, not a new entry)")
    if ok and guardrails.is_opening(order):
        ok, why = dailyloss.check(account_record(args.get("account_number")), date.today().isoformat(),
                                  cfg["limits"].get("max_daily_loss_pct", dailyloss.DEFAULT_PCT))
        reason = reason if ok else why
    _decide("allow" if ok else "deny", reason)


def post(event: dict) -> None:
    tool, args = event.get("tool_name", ""), event.get("tool_input") or {}
    name = tool.rsplit("__", 1)[-1]
    if name == "get_portfolio":
        return record_portfolio(args, event.get("tool_response"))
    if name in ("get_equity_orders", "get_option_orders"):
        if not paths.ready(LEDGER):
            return
        rows = releases(event.get("tool_response"), _rows_today())
        if rows:
            with open(LEDGER, "a") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
        return
    if classify(tool) != "order" or not paths.ready(LEDGER):
        return  # (no private/ yet: pre refuses every order until `rhgex init`, so there's nothing to count)
    # The ledger is synced through git, so rows carry only what the daily caps need: no account number and
    # no raw response.
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "date": date.today().isoformat(),
             "tool": tool.rsplit("__", 1)[-1], "order_id": order_id(event.get("tool_response"))}
    try:
        order = normalize(tool, args)
        entry["symbol"], entry["side"] = order["symbol"], order["side"]
        entry["opening"] = guardrails.is_opening(order)
        entry["cost_usd"] = guardrails.cost(order) if entry["opening"] else 0
    except Exception as e:
        entry["opening"], entry["parse_error"] = True, str(e)  # count it against the daily cap anyway
    paths.ensure(LEDGER.parent)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def main(stage: str) -> None:
    event = json.load(sys.stdin)
    if stage == "pre":
        try:
            pre(event)
        except Exception as e:  # any bug denies the call rather than letting it through
            _decide("deny", f"hook error {type(e).__name__}: {e}")
    else:
        post(event)
