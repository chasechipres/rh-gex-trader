"""Pre-trade checklist: every mechanical entry rule from CLAUDE.md, checked before `plan add`.

`rhgex preflight` prints one line per check and exits 1 if any fails. It doesn't decide whether to trade (thesis,
trend, GEX and fundamentals stay judgment calls); it makes sure no mechanical rule is skipped. Option legs are
passed in from live Robinhood quotes (`--leg BID,ASK,OI`), so liquidity is checked on real numbers.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import exits

MAX_OPEN_AT_RISK = 5      # open positions whose stop is still below breakeven
MAX_PER_SECTOR = 2        # open positions in one sector
MAX_SPREAD_PCT = 10.0     # each leg's bid/ask spread, % of its mid ...
MIN_SPREAD = 0.05         # ... or this many dollars, whichever is wider (a nickel is tight on a cheap leg)
MIN_OPEN_INTEREST = 500   # the leg you buy (the first --leg)
MIN_SHORT_OPEN_INTEREST = 100  # a spread's sold leg: further out of the money, so thinner
DTE_RANGE = (14, 45)      # preferred days to expiry for options
PRE_EARNINGS_MIN_DTE = 7  # shorter expiries are allowed when they end before an earnings report inside the range
FRESH_POST_DAYS = 2       # trading days
REVENGE_DAYS = 2          # trading days after a losing exit
EARNINGS_SOON_DAYS = 3    # trading days, for shares
STATUS_RE = re.compile(r"/status/(\d+)")


@dataclass
class Candidate:
    symbol: str
    direction: str
    price: float
    stop: float
    target: float
    asset: str = "option"
    expiration: str | None = None
    legs: list[tuple[float, float, int]] = field(default_factory=list)  # (bid, ask, open interest)
    source: str = ""
    earnings_play: bool = False
    new_setup: bool = False


@dataclass
class Context:
    today: date
    blocks: dict[str, str]
    plans: list[dict]                 # open plans
    journal: list[dict]
    posts: dict[str, date]            # status id -> date of the note it's saved in
    opened_today: int                 # opening orders in today's ledger
    max_new_per_day: int
    earnings: object = None           # symbol -> date | None
    sector: object = None             # symbol -> str | None


def _days_ago(d: date, today: date) -> int:
    return exits.trading_days_until(today, d) if d <= today else 0


def leg_liquidity(bid: float, ask: float, oi: int, short: bool = False) -> tuple[bool, str]:
    """Whether one option leg is liquid enough to trade, and why. short: the sold leg of a spread."""
    mid = (bid + ask) / 2
    spread = ask - bid
    max_spread = max(mid * MAX_SPREAD_PCT / 100, MIN_SPREAD)
    min_oi = MIN_SHORT_OPEN_INTEREST if short else MIN_OPEN_INTEREST
    ok = mid > 0 and spread <= max_spread + 1e-9 and oi >= min_oi
    pct = spread / mid * 100 if mid > 0 else 100.0
    return ok, (f"spread ${spread:.2f} = {pct:.1f}% of mid (max {MAX_SPREAD_PCT:g}% or ${MIN_SPREAD:.2f}), "
                f"OI {oi} (min {min_oi})")


def at_risk(plan: dict) -> bool:
    """A position that can still lose: its stop hasn't reached breakeven."""
    entry = plan.get("price")
    if entry is None:
        return True
    return plan["stop"] < entry if plan["direction"] == "bullish" else plan["stop"] > entry


def evaluate(c: Candidate, ctx: Context) -> list[dict]:
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": ok, "detail": detail})

    sym = c.symbol.upper()
    add("blocked", sym not in ctx.blocks, ctx.blocks.get(sym, "not blocked"))

    try:
        rr = exits.reward_risk(c.direction, c.price, c.stop, c.target)
        add("reward_risk", rr >= exits.MIN_REWARD_RISK, f"{rr} (min {exits.MIN_REWARD_RISK})")
    except ValueError as e:
        add("reward_risk", False, str(e))

    er = ctx.earnings(sym) if ctx.earnings else None
    if c.asset == "option":
        if not c.expiration:
            add("expiration", False, "options need --expiration")
        else:
            exp = date.fromisoformat(c.expiration)
            dte = (exp - ctx.today).days
            lo, hi = DTE_RANGE
            # earnings season: when a report lands inside the usual window, an expiry before it may be shorter
            pre_earnings = (er is not None and PRE_EARNINGS_MIN_DTE <= dte < lo and exp < er
                            and (er - ctx.today).days <= hi)
            add("dte", lo <= dte <= hi or pre_earnings,
                f"{dte} days (prefer {lo}-{hi}" + (f"; {PRE_EARNINGS_MIN_DTE}+ ok before earnings {er})"
                                                   if pre_earnings else ")"))
            inside = er is not None and ctx.today <= er <= exp
            add("earnings", not inside or c.earnings_play,
                f"earnings {er} before expiry {exp}" + (" (earnings play)" if inside and c.earnings_play else "")
                if inside else f"next earnings {er}")
        if not c.legs:
            add("liquidity", False, "pass each leg's live quote as --leg BID,ASK,OI")
        for i, (bid, ask, oi) in enumerate(c.legs, 1):
            add(f"liquidity_leg{i}", *leg_liquidity(bid, ask, oi, short=i > 1))
    else:
        soon = er is not None and ctx.today <= er and exits.trading_days_until(er, ctx.today) <= EARNINGS_SOON_DAYS
        add("earnings", not soon or c.earnings_play, f"next earnings {er}")

    risky = [p["symbol"] for p in ctx.plans if at_risk(p)]
    add("open_risk", len(risky) < MAX_OPEN_AT_RISK,
        f"{len(risky)} open positions still at risk (max {MAX_OPEN_AT_RISK}): {', '.join(risky) or 'none'}")

    if ctx.sector:
        mine = ctx.sector(sym)
        same = [p["symbol"] for p in ctx.plans if mine and ctx.sector(p["symbol"]) == mine]
        add("sector", len(same) < MAX_PER_SECTOR,
            f"{mine or 'unknown sector'}: {len(same)} open ({', '.join(same) or 'none'}), max {MAX_PER_SECTOR}; "
            "themes (AI, crypto miners) are your call")

    ids = STATUS_RE.findall(c.source or "")
    dates = [ctx.posts[i] for i in ids if i in ctx.posts]
    if not dates:
        add("fresh_post", False, "source must link a post saved in private/notes/posts/")
    else:
        newest = max(dates)
        age = _days_ago(newest, ctx.today)
        add("fresh_post", age <= FRESH_POST_DAYS, f"post from {newest}, {age} trading days ago (max {FRESH_POST_DAYS})")

    losses = [e for e in ctx.journal if e["symbol"] == sym and e["action"] == "exit" and (e.get("pnl") or 0) < 0
              and _days_ago(date.fromisoformat(e["time"][:10]), ctx.today) <= REVENGE_DAYS]
    add("revenge", not losses or c.new_setup,
        f"losing exit {losses[-1]['time'][:10]}" + (" (new setup)" if losses and c.new_setup else "")
        if losses else "no recent losing exit")

    add("daily_count", ctx.opened_today < ctx.max_new_per_day,
        f"{ctx.opened_today} opened today (max {ctx.max_new_per_day})")
    return checks


def saved_posts(posts_dir: Path) -> dict[str, date]:
    """status id -> date of the earliest note it appears in (notes are named YYYY-MM-DD-HHMM-slug.md)."""
    out: dict[str, date] = {}
    for p in sorted(posts_dir.glob("*.md")):
        try:
            d = date.fromisoformat(p.name[:10])
        except ValueError:
            continue
        for i in STATUS_RE.findall(p.read_text(encoding="utf-8")):
            out.setdefault(i, d)
    return out
