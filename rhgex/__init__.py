"""rh-gex-trader: research tools for a Claude Code session that trades on Robinhood via MCP.

  research  technicals + fundamentals (+ GEX profile with --gex) for one or more tickers
  gex       estimated gamma exposure profile: regime, zero-gamma flip, call/put walls
  fit       option structures (calls/puts, debit verticals) that fit the risk budget and pass liquidity
  check     dry-run an order (JSON) through the exact PreToolUse hook
  blocks    show active wash-sale blocks, logged wash-sale windows and limits
  wash      log a loss exit and its 30-day wash-sale window (logging only), or list them
  watch     price triggers for journaled watches, checked every exit check
  calls     the source's calls, scored: hit rate by setup type
  journal   log a trade thesis or decision to private/logs/journal.jsonl
  record    track record: live realized P/L and win rate by confidence (--readme updates private/README.md)
  preflight pre-trade checklist: every mechanical entry rule, before plan add
  size      contracts or shares for a fixed % risk of the account
  lev       leveraged funds: a stock's funds, or a fund's stop/target and size
  lock      one machine at a time: acquire|release|status the session lock
  peak      drawdown baseline: show, or reset (owner only)
  init      set up private/ (your limits, notes, journal, plans); --github, --clone, --migrate, --check
  sync      commit private/, then pull and push it when it has a remote
  hook      (used by Claude Code hooks) pre|post
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from . import paths

LOG_DIR = paths.LOGS


def out(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_research(args) -> None:
    from . import gex, guardrails, market, washlog

    blocks = guardrails.active_blocks(guardrails.load(), date.today())
    windows = washlog.warnings()
    results = []
    for sym in args.symbols:
        sym = sym.upper().lstrip("$")
        r = {"symbol": sym}
        if sym in blocks:
            r["wash_sale_blocked"] = blocks[sym]
        if sym in windows:
            r["wash_sale_window"] = windows[sym]
        try:
            r["technicals"] = market.technicals(sym)
            r["fundamentals"] = market.fundamentals(sym)
            if args.gex:
                r["gex"] = gex.profile(sym)
        except Exception as e:
            r["error"] = f"{type(e).__name__}: {e}"
        results.append(r)
    out(results)


def cmd_gex(args) -> None:
    from . import gex

    out([gex.profile(s.upper().lstrip("$"), args.days) for s in args.symbols])


def cmd_fit(args) -> None:
    from . import fit

    out(fit.scan(args.symbol.upper().lstrip("$"), args.direction, args.target, args.budget, args.min_dte,
                 args.max_dte, args.top))


def cmd_check(args) -> None:
    """Dry-run the exact PreToolUse hook (limits, exit plan, daily loss stop) on an order."""
    import io
    from contextlib import redirect_stdout
    from . import hook

    order_args = json.loads(args.order_json)
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            hook.pre({"tool_name": f"mcp__robinhood-trading__{args.tool}", "tool_input": order_args})
        except Exception as e:  # what hook.main does: any error denies
            hook._decide("deny", f"hook error {type(e).__name__}: {e}")
    decision = json.loads(buf.getvalue())["hookSpecificOutput"]
    ok = decision["permissionDecision"] == "allow"
    try:
        normalized = hook.normalize(args.tool, order_args)
    except Exception:
        normalized = None
    out({"ok": ok, "reason": decision["permissionDecisionReason"], "normalized": normalized})
    sys.exit(0 if ok else 1)


def cmd_preflight(args) -> None:
    from functools import lru_cache
    from . import exits, guardrails, hook, market, preflight, record

    cfg = guardrails.load()
    legs = []
    for leg in args.leg:
        bid, ask, oi = leg.split(",")
        legs.append((float(bid), float(ask), int(oi)))
    c = preflight.Candidate(args.symbol, args.direction, args.price, args.stop, args.target, args.asset,
                            args.expiration, legs, args.source, args.earnings_play, args.new_setup,
                            tuple(float(x) for x in args.quote.split(",")) if args.quote else None)
    ctx = preflight.Context(
        today=date.today(), blocks=guardrails.active_blocks(cfg, date.today()),
        plans=exits.open_plans(exits.load()), journal=record.load(), posts=preflight.saved_posts(POSTS_DIR),
        opened_today=sum(1 for r in hook.ledger_today() if r.get("opening")),
        max_new_per_day=cfg["limits"].get("max_new_positions_per_day", 3),
        earnings=lru_cache(None)(market.next_earnings),
        sector=lru_cache(None)(lambda s: market.fundamentals(s).get("sector")),
        dollar_volume=market.dollar_volume)
    checks = preflight.evaluate(c, ctx)
    for ch in checks:
        print(f"{'PASS' if ch['ok'] else 'FAIL'}  {ch['check']:<16} {ch['detail']}")
    failed = [ch["check"] for ch in checks if not ch["ok"]]
    print(f"\n{'all checks pass' if not failed else 'FAILED: ' + ', '.join(failed)}")
    sys.exit(1 if failed else 0)


def cmd_lock(args) -> None:
    from . import lock

    if args.action == "acquire":
        try:
            out(lock.acquire())
        except ValueError as e:
            sys.exit(f"refused: {e}")
    elif args.action == "release":
        out(lock.release())
    else:
        out({"machine": lock.machine(), "lock": lock.read()})


def cmd_peak(args) -> None:
    """Show the drawdown baseline, or (owner only) reset it after reviewing a drawdown pause."""
    from . import dailyloss, hook

    accounts = json.loads(hook.ACCOUNT.read_text()) if hook.ACCOUNT.exists() else {}
    if args.action == "reset":
        accounts = {a: dailyloss.reset_peak(r) for a, r in accounts.items() if r.get("total_value")}
        hook.ACCOUNT.write_text(json.dumps(accounts, indent=2))
    out({a: {k: r.get(k) for k in ("date", "total_value", "start_value", "peak_value")} for a, r in accounts.items()})


def order_cap(account: float) -> float | None:
    """The hook's per-order dollar cap for this account value, or None without a guardrails.toml."""
    from . import guardrails

    if not guardrails.CONFIG.exists():
        return None
    try:
        return guardrails.limit(guardrails.load()["limits"], "order", account)
    except ValueError:
        return None


def cmd_lev(args) -> None:
    from . import leveraged, sizing

    sym = args.symbol.upper()
    fund = leveraged.underlying(sym)
    if not fund:
        out({"stock": sym, "funds": {f: leveraged.FUNDS[f][1] for f in leveraged.funds_for(sym)}})  # fund -> leverage
        return
    stock, lev = fund
    res = {"fund": sym, "underlying": stock, "leverage": lev}
    if args.fund_price is not None and args.price is not None:
        conv = lambda lvl: leveraged.fund_level(args.fund_price, args.price, lvl, lev)  # noqa: E731
        res.update({k: conv(v) for k, v in (("fund_stop", args.stop), ("fund_target", args.target)) if v is not None})
        if args.account is not None and "fund_stop" in res:
            try:
                res["size"] = sizing.shares(args.account, args.fund_price, res["fund_stop"],
                                            args.pct or sizing.SHARE_RISK_PCT, max_cost=order_cap(args.account))
            except ValueError as e:
                sys.exit(f"refused: {e}")
    out(res)


def cmd_size(args) -> None:
    from . import sizing

    try:
        if args.option_cost is not None:
            out(sizing.option_contracts(args.account, args.option_cost, args.pct or sizing.OPTION_RISK_PCT))
        elif args.entry is not None and args.stop is not None:
            out(sizing.shares(args.account, args.entry, args.stop, args.pct or sizing.SHARE_RISK_PCT,
                              max_cost=order_cap(args.account)))
        else:
            sys.exit("refused: pass --option-cost, or --entry and --stop")
    except ValueError as e:
        sys.exit(f"refused: {e}")


def cmd_blocks(args) -> None:
    from . import guardrails, hook, washlog

    cfg = guardrails.load()
    accounts = json.loads(hook.ACCOUNT.read_text()) if hook.ACCOUNT.exists() else {}
    dollars = {}
    for acct in accounts:
        try:
            dollars[acct] = {n: guardrails.limit(cfg["limits"], n, hook.account_value(acct))
                             for n in ("order", "option_premium", "daily_deployed")}
        except ValueError as e:
            dollars[acct] = str(e)
    out({"active_blocks": guardrails.active_blocks(cfg, date.today()), "wash_sale_windows": washlog.active(),
         "limits": cfg["limits"],
         "account_values": accounts, "dollar_limits_today": dollars, "today_ledger": hook.ledger_today()})


def cmd_plan(args) -> None:
    from . import exits

    try:
        if args.action == "add":
            out(exits.add(args.symbol, args.asset, args.direction, args.stop, args.target, args.thesis,
                          args.expiration, args.premium_stop, price=args.price, existing=args.existing))
        elif args.action == "close":
            out(exits.close(args.symbol, args.reason))
        elif args.action == "raise-stop":
            out(exits.raise_stop(args.symbol, args.stop))
        else:
            out(exits.open_plans(exits.load()))
    except ValueError as e:
        sys.exit(f"refused: {e}")


def cmd_exits(args) -> None:
    from . import exits

    prices = dict((k, float(v)) for k, v in (p.split("=") for p in args.price))
    out(exits.check(prices))


def cmd_watch(args) -> None:
    from . import watches

    try:
        if args.action == "add":
            side, level = ("above", args.above) if args.above is not None else ("below", args.below)
            out(watches.add(args.symbol, side, level, args.note, args.until, args.source))
        elif args.action == "close":
            out(watches.close(args.symbol, args.reason))
        elif args.action == "check":
            out(watches.check(dict((k, float(v)) for k, v in (p.split("=") for p in args.price))))
        else:
            out(watches.open_watches(watches.load()))
    except ValueError as e:
        sys.exit(f"refused: {e}")


def cmd_wash(args) -> None:
    from . import washlog

    if args.action == "list":
        return out(washlog.load() if args.all else washlog.active())
    try:
        out(washlog.add(args.symbol, args.loss, args.date, args.asset, args.contract, args.note))
    except ValueError as e:
        sys.exit(f"refused: {e}")


POSTS_DIR = paths.POSTS
STATUS_RE = re.compile(r"(?:x|twitter)\.com/\w+/status/(\d+)")


def check_source(action: str, source: str, posts_dir: Path = POSTS_DIR) -> None:
    """A decision cites the post behind it, and every X post it links must be saved in private/notes/posts/."""
    ids = STATUS_RE.findall(source or "")
    if action in ("trade", "skip", "watch") and not ids:
        raise ValueError("--source must link the X post behind this decision (one saved in private/notes/posts/)")
    saved = "\n".join(p.read_text(encoding="utf-8") for p in posts_dir.glob("*.md"))
    missing = [i for i in ids if f"/status/{i}" not in saved]
    if missing:
        raise ValueError(f"post {', '.join(missing)} isn't in any private/notes/posts/ file; save the post first or fix the link")


def cmd_journal(args) -> None:
    try:
        check_source(args.action, args.source)
    except ValueError as e:
        sys.exit(f"refused: {e}")
    if args.action == "trade" and not args.type:
        sys.exit("refused: a trade entry needs --type (shares, lev-long, inverse, call, put or spread) for the track record")
    try:
        paths.ensure(LOG_DIR)
    except FileNotFoundError as e:
        sys.exit(f"refused: {e}")
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "symbol": args.symbol.upper(),
             "action": args.action, "confidence": args.confidence, "thesis": args.thesis,
             "source": args.source}
    if args.action == "trade":
        entry["type"] = args.type
    if args.action == "exit" and args.pnl is not None:
        entry["pnl"], entry["pnl_pct"] = round(args.pnl, 2), args.pnl_pct
    with open(LOG_DIR / "journal.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    out(entry)


def cmd_calls(args) -> None:
    from . import calls

    if args.action == "add":
        try:
            check_source("trade", args.source)
            out(calls.add(args.symbol, args.direction, args.setup, args.level, args.target, args.invalid,
                          args.source, args.by, args.posted, args.note))
        except ValueError as e:
            sys.exit(f"refused: {e}")
    elif args.action == "check":
        out(calls.check())
    elif args.action == "stats":
        out(calls.stats(calls.load()))
    else:
        out([c for c in calls.load() if c["result"] == "open"])


def cmd_record(args) -> None:
    from . import exits, record

    s = record.summarize(record.load(), exits.load())
    if args.readme:
        record.write_readme(record.render(s, args.account_value))
    out(s)


def cmd_init(args) -> None:
    from . import init

    try:
        out(init.status() if args.check else init.init(args.clone, args.github, args.migrate, rev=args.rev))
    except (ValueError, OSError) as e:
        sys.exit(f"refused: {e}")
    except subprocess.CalledProcessError as e:
        sys.exit(f"failed: {' '.join(e.cmd)}\n{e.stderr or ''}")


def cmd_sync(args) -> None:
    from . import init

    try:
        out(init.sync(args.message, args.pull))
    except ValueError as e:
        sys.exit(f"refused: {e}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("research")
    r.add_argument("symbols", nargs="+")
    r.add_argument("--gex", action="store_true", help="include the GEX profile (slower)")

    g = sub.add_parser("gex")
    g.add_argument("symbols", nargs="+")
    g.add_argument("--days", type=int, default=45, help="max days to expiry to include")

    ft = sub.add_parser("fit", help="liquid calls/puts and debit verticals that fit the risk budget")
    ft.add_argument("symbol")
    ft.add_argument("--direction", choices=["bullish", "bearish"], required=True)
    ft.add_argument("--target", type=float, required=True, help="underlying target")
    ft.add_argument("--budget", type=float, required=True, help="max loss per contract in dollars (`size` budget)")
    ft.add_argument("--min-dte", type=int, default=14)
    ft.add_argument("--max-dte", type=int, default=45)
    ft.add_argument("--top", type=int, default=10)

    c = sub.add_parser("check")
    c.add_argument("tool", choices=sorted(["place_equity_order", "place_option_order"]))
    c.add_argument("order_json", help="the tool's arguments as JSON, exactly as you'd send them")

    pf = sub.add_parser("preflight", help="pre-trade checklist: every mechanical entry rule, before plan add")
    pf.add_argument("symbol")
    pf.add_argument("--direction", choices=["bullish", "bearish"], required=True)
    pf.add_argument("--price", type=float, required=True, help="underlying's live price")
    pf.add_argument("--stop", type=float, required=True, help="underlying stop")
    pf.add_argument("--target", type=float, required=True, help="underlying target")
    pf.add_argument("--asset", choices=["option", "stock"], default="option")
    pf.add_argument("--expiration", help="option expiry YYYY-MM-DD")
    pf.add_argument("--leg", action="append", default=[], help="each option leg's live BID,ASK,OPEN_INTEREST")
    pf.add_argument("--quote", help="a leveraged fund's live BID,ASK (shares of a fund in rhgex/leveraged.py)")
    pf.add_argument("--source", default="", help="the X post link behind the idea (saved in private/notes/posts/)")
    pf.add_argument("--earnings-play", action="store_true", help="the earnings report is the point of the trade")
    pf.add_argument("--new-setup", action="store_true", help="re-entry after a stop-out on a new post with new levels")

    lk = sub.add_parser("lock", help="one machine at a time: acquire before orders, release at the end")
    lk.add_argument("action", choices=["acquire", "release", "status"])

    pk = sub.add_parser("peak", help="drawdown baseline: show it, or reset it (owner only, after a review)")
    pk.add_argument("action", choices=["show", "reset"])

    sz = sub.add_parser("size", help="contracts or shares so a full loss is a fixed % of the account")
    sz.add_argument("--account", type=float, required=True, help="account value from get_portfolio")
    sz.add_argument("--option-cost", type=float, help="max loss per contract in dollars (premium x 100)")
    sz.add_argument("--entry", type=float, help="shares: entry price")
    sz.add_argument("--stop", type=float, help="shares: stop price")
    sz.add_argument("--pct", type=float, help="override the risk %% (default 5)")

    lv = sub.add_parser("lev", help="leveraged funds: a stock's funds, or a fund's stop/target and size")
    lv.add_argument("symbol", help="a stock (lists its funds) or a fund")
    lv.add_argument("--fund-price", type=float, help="the fund's live price")
    lv.add_argument("--price", type=float, help="the stock's live price")
    lv.add_argument("--stop", type=float, help="the plan's stop, on the stock")
    lv.add_argument("--target", type=float, help="the plan's target, on the stock")
    lv.add_argument("--account", type=float, help="account value: also size the fund order")
    lv.add_argument("--pct", type=float, help="override the risk %% (default 5)")

    sub.add_parser("blocks")

    pl = sub.add_parser("plan", help="exit plans: add before entry, raise-stop as it works, close after exit, list")
    pl.add_argument("action", choices=["add", "raise-stop", "close", "list"])
    pl.add_argument("symbol", nargs="?", default="")
    pl.add_argument("--asset", choices=["stock", "option"], default="stock")
    pl.add_argument("--direction", choices=["bullish", "bearish"], default="bullish",
                    help="direction of the UNDERLYING move you need (puts are bearish)")
    pl.add_argument("--stop", type=float, help="underlying price where the thesis is wrong")
    pl.add_argument("--target", type=float, help="underlying price to take profit")
    pl.add_argument("--expiration", help="option expiry YYYY-MM-DD")
    pl.add_argument("--premium-stop", type=float, help="option premium for the resting stop order")
    pl.add_argument("--price", type=float, help="underlying's current price; reward:risk is checked from it")
    pl.add_argument("--existing", action="store_true",
                    help="rebuild the plan for a position already held (skips the reward:risk check)")
    pl.add_argument("--thesis", default="")
    pl.add_argument("--reason", default="", help="why the position was closed (for close)")

    ex = sub.add_parser("exits", help="check open plans against current prices")
    ex.add_argument("--price", action="append", default=[], help="SYMBOL=PX override, e.g. from Robinhood quotes")

    wt = sub.add_parser("watch", help="price triggers for journaled watches: add, check (every exit check), close, list")
    wt.add_argument("action", choices=["add", "check", "close", "list"])
    wt.add_argument("symbol", nargs="?", default="")
    side = wt.add_mutually_exclusive_group()
    side.add_argument("--above", type=float, help="fires when the underlying is at or above this")
    side.add_argument("--below", type=float, help="fires when the underlying is at or below this")
    wt.add_argument("--until", help="last live day YYYY-MM-DD (default: 2 trading days)")
    wt.add_argument("--note", default="", help="what to do when it fires")
    wt.add_argument("--source", default="", help="the post behind the watch")
    wt.add_argument("--price", action="append", default=[], help="check: SYMBOL=PX from Robinhood quotes")
    wt.add_argument("--reason", default="", help="close: why")

    w = sub.add_parser("wash", help="log a loss exit's 30-day wash-sale window (logging only), or list them")
    w.add_argument("action", choices=["add", "list"])
    w.add_argument("symbol", nargs="?", default="", help="the underlying, e.g. XYZ for an XYZ put")
    w.add_argument("--loss", type=float, help="realized loss in dollars, as a positive number")
    w.add_argument("--date", help="sale date YYYY-MM-DD (default today)")
    w.add_argument("--asset", choices=["stock", "option"], default="stock")
    w.add_argument("--contract", default="", help="for options, e.g. 'XYZ 2026-11-20 100P' or '100/95P'")
    w.add_argument("--note", default="")
    w.add_argument("--all", action="store_true", help="list: include windows that have ended")

    j = sub.add_parser("journal")
    j.add_argument("symbol")
    j.add_argument("action", choices=["trade", "skip", "watch", "exit"])
    j.add_argument("--thesis", required=True)
    j.add_argument("--confidence", type=float, required=True, help="0-1")
    j.add_argument("--source", default="", help="e.g. the X post date/link the idea came from")
    j.add_argument("--type", choices=["shares", "lev-long", "inverse", "call", "put", "spread"],
                   help="trade (required): what was bought, for the track record's by-type split")
    j.add_argument("--pnl", type=float, help="exit: realized P/L in dollars (negative for a loss)")
    j.add_argument("--pnl-pct", type=float, help="exit: realized P/L as a % of the position's cost")

    cl = sub.add_parser("calls", help="the source's calls, scored on daily highs/lows: add, check, stats, list")
    cl.add_argument("action", choices=["add", "check", "stats", "list"])
    cl.add_argument("symbol", nargs="?", default="")
    cl.add_argument("--direction", choices=["bullish", "bearish"])
    cl.add_argument("--setup", choices=["uptrend-dip", "downtrend-dip", "breakdown", "breakout", "range", "other"])
    cl.add_argument("--level", type=float, help="the level the call is made from (pivot, entry, king)")
    cl.add_argument("--target", type=float, help="his target")
    cl.add_argument("--invalid", type=float, help="the price that proves the call wrong")
    cl.add_argument("--by", help="deadline YYYY-MM-DD (default: 5 trading days after the post)")
    cl.add_argument("--posted", help="'YYYY-MM-DD HH:MM' local time, as in the post note's name (default now); "
                    "a date alone only for a post made before the open")
    cl.add_argument("--source", default="", help="the post link (saved in private/notes/posts/)")
    cl.add_argument("--note", default="")

    rec = sub.add_parser("record", help="track record: live realized P/L")
    rec.add_argument("--readme", action="store_true", help="rewrite the track-record block in private/README.md")
    rec.add_argument("--account-value", type=float, help="current account value (from get_portfolio)")

    it = sub.add_parser("init", help="set up private/ (your limits, notes, journal, plans); safe to re-run")
    it.add_argument("--github", nargs="?", const="rh-gex-trader-private", default="", metavar="NAME",
                    help="also create a private GitHub repo (default: <your gh login>/rh-gex-trader-private) and push to it")
    it.add_argument("--clone", nargs="?", const="auto", default="", metavar="URL",
                    help="another machine: clone your private repo (default: <your gh login>/rh-gex-trader-private)")
    it.add_argument("--migrate", action="store_true", help="copy files from before the split into private/")
    it.add_argument("--from", dest="rev", default="", metavar="REV",
                    help="with --migrate: read the old files from this commit (e.g. the last one before the split)")
    it.add_argument("--check", action="store_true", help="only report what's set up and what's missing")

    sy = sub.add_parser("sync", help="commit private/, then pull and push it when it has a remote")
    sy.add_argument("-m", "--message", default="cycle: notes, journal, plans", help="commit message")
    sy.add_argument("--pull", action="store_true", help="only pull (start of an exit check)")

    h = sub.add_parser("hook")
    h.add_argument("stage", choices=["pre", "post"])

    args = p.parse_args()
    if args.cmd == "hook":
        from . import hook
        return hook.main(args.stage)
    if args.cmd == "plan" and args.action != "list" and not args.symbol:
        p.error("plan add/close needs a symbol")
    if args.cmd == "plan" and args.action == "add" and (args.stop is None or args.target is None):
        p.error("plan add needs --stop and --target")
    if args.cmd == "watch" and args.action in ("add", "close") and not args.symbol:
        p.error("watch add/close needs a symbol")
    if args.cmd == "watch" and args.action == "add" and args.above is None and args.below is None:
        p.error("watch add needs --above or --below")
    if args.cmd == "calls" and args.action == "add" and (
            not args.symbol or None in (args.direction, args.setup, args.level, args.target, args.invalid)):
        p.error("calls add needs a symbol, --direction, --setup, --level, --target and --invalid")
    if args.cmd == "wash" and args.action == "add" and (not args.symbol or args.loss is None):
        p.error("wash add needs a symbol and --loss")
    {"research": cmd_research, "gex": cmd_gex, "check": cmd_check, "blocks": cmd_blocks,
     "fit": cmd_fit, "plan": cmd_plan, "exits": cmd_exits, "wash": cmd_wash, "watch": cmd_watch, "journal": cmd_journal,
     "record": cmd_record, "calls": cmd_calls, "size": cmd_size, "lev": cmd_lev,
     "lock": cmd_lock, "peak": cmd_peak, "preflight": cmd_preflight, "init": cmd_init, "sync": cmd_sync}[args.cmd](args)
