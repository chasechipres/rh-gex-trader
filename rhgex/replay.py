"""Replay the source's dip calls on 15-minute bars: what each way of trading them would have done.

`rhgex replay` reads private/logs/calls.json and, for every bullish dip call posted in the window (setup
`downtrend-dip` by default), simulates:

- **dip:** buy at his level when price first touches it, sell by 15:45 ET that day
- **reclaim:** the CLAUDE.md rule: after a touch, a 15-minute close back above the level on above-average volume
  by 15:30 ET, without trading through the call's invalidation first; R:R >= 1.5 from the entry; sold by 15:45 ET
- **reclaim-held:** the same entry, held until the stop, the target or the call's deadline

The stop is the call's invalidation (`invalid_from` says whether it's his or the half-ATR one), the target his.
Sizing is the real one (5% risk, capped by the per-order limit), so results are in dollars and in R. Each trade
records the market's move from its open at entry (SPY, as data only), so the weekly review can test a market
filter on many calls before anyone adds one.

Limits: a bar that touches both the stop and the target counts as the stop; fills are at the level or the bar's
close with no slippage, so real results will be somewhat worse. Yahoo keeps 15-minute bars for about 60 days.
"""

from datetime import date, datetime, timedelta

from . import calls as calls_mod
from . import exits, sizing
from .monitor import ET, hhmm

MARKET = "SPY"
SAME_DAY_EXIT, RECLAIM_BY, VOLUME_BARS = "15:45", "15:30", 20
VARIANTS = ("dip", "reclaim", "reclaim-held")


def _end(b: dict) -> datetime:
    return b["start"] + timedelta(minutes=15)


def posted_time(call: dict) -> datetime:
    """The post's time in ET; a call logged with a date alone was posted before that day's open."""
    if call.get("posted_at"):
        return datetime.fromisoformat(call["posted_at"]).astimezone(ET)  # naive = this machine's local time
    return datetime.combine(date.fromisoformat(call["posted"]), datetime.min.time(), ET)


def walk(bars: list[dict], i: int, entry: float, stop: float, target: float, held: bool, deadline: date):
    """Exit after bar i: (price, reason, bar index). Stop wins a bar that touches both."""
    day = bars[i]["start"].date()
    for j in range(i + 1, len(bars)):
        b = bars[j]
        d = b["start"].date()
        if held and d > deadline:
            return bars[j - 1]["close"], "deadline", j - 1
        if not held and (d != day or hhmm(b["start"]) >= SAME_DAY_EXIT):
            return (b["open"], "15:45", j) if d == day else (bars[j - 1]["close"], "close", j - 1)
        if b["open"] <= stop:
            return b["open"], "stop (gap)", j
        if b["low"] <= stop:
            return stop, "stop", j
        if b["high"] >= target:
            return target, "target", j
    return bars[-1]["close"], "open at end of data", len(bars) - 1


def market_move(spy: list[dict], when: datetime) -> float | None:
    """SPY's % change from that day's open to the close of the bar starting at `when`."""
    day = [b for b in spy if b["start"].date() == when.date()]
    at = next((b for b in day if b["start"] == when), None)
    return round((at["close"] / day[0]["open"] - 1) * 100, 2) if at and day else None


def _trade(bars, i, entry, stop, target, held, deadline, account, max_cost, spy):
    x, why, j = walk(bars, i, entry, stop, target, held, deadline)
    size = sizing.shares(account, entry, stop, max_cost=max_cost)
    return {"entry": round(entry, 2), "when": bars[i]["start"].strftime("%a %m-%d %H:%M"), "exit": round(x, 2),
            "why": why, "shares": size["shares"], "pnl": round(size["shares"] * (x - entry), 2),
            "r": round((x - entry) / (entry - stop), 2), "market_pct": market_move(spy, bars[i]["start"])}


def simulate(call: dict, bars: list[dict], spy: list[dict], account: float, max_order_pct: float = 75) -> dict:
    """Every variant for one bullish call. bars: 15-minute regular-hours bars (start tz-aware, open/high/low/
    close/volume), oldest first, including at least VOLUME_BARS before the post."""
    level, target, stop = call["level"], call["target"], call["invalid"]
    deadline, max_cost = date.fromisoformat(call["by"]), account * max_order_pct / 100
    t0 = posted_time(call)
    live = [i for i, b in enumerate(bars) if _end(b) > t0 and b["start"].date() <= deadline]
    out = {v: "skip: never touched his level" for v in VARIANTS}
    touch = next((i for i in live if bars[i]["low"] <= level), None)
    if touch is None:
        return out
    tb = bars[touch]
    entry = min(level, tb["open"])
    if tb["open"] <= stop:
        out["dip"] = "skip: gapped through the stop"
    elif hhmm(tb["start"]) >= SAME_DAY_EXIT:
        out["dip"] = "skip: touched after 15:45"
    elif (rr := (target - entry) / (entry - stop)) < exits.MIN_REWARD_RISK:
        out["dip"] = f"skip: R:R {rr:.2f}"
    elif tb["low"] <= stop:
        size = sizing.shares(account, entry, stop, max_cost=max_cost)
        out["dip"] = {"entry": round(entry, 2), "when": tb["start"].strftime("%a %m-%d %H:%M"), "exit": stop,
                      "why": "stop (same bar)", "shares": size["shares"],
                      "pnl": round(size["shares"] * (stop - entry), 2), "r": -1.0,
                      "market_pct": market_move(spy, tb["start"])}
    else:
        out["dip"] = _trade(bars, touch, entry, stop, target, False, deadline, account, max_cost, spy)
    for k in (i for i in live if i >= touch):
        b = bars[k]
        if b["low"] <= stop:
            out["reclaim"] = out["reclaim-held"] = "skip: traded through the stop first"
            break
        before = bars[max(0, k - VOLUME_BARS):k]
        if (b["close"] > level and len(before) == VOLUME_BARS and hhmm(_end(b)) <= RECLAIM_BY
                and b["volume"] > sum(x["volume"] for x in before) / VOLUME_BARS):
            e = b["close"]
            if (rr := (target - e) / (e - stop)) < exits.MIN_REWARD_RISK:
                out["reclaim"] = out["reclaim-held"] = f"skip: R:R {rr:.2f} at {b['start'].strftime('%a %H:%M')}"
            else:
                for v, held in (("reclaim", False), ("reclaim-held", True)):
                    out[v] = _trade(bars, k, e, stop, target, held, deadline, account, max_cost, spy)
            break
    else:
        out["reclaim"] = out["reclaim-held"] = "skip: no confirmed reclaim"
    return out


def summarize(rows: list[dict]) -> dict:
    """Per variant: all trades, then split by stop source and by the market's direction at entry."""
    def group(ts):
        pnl = [t["pnl"] for t in ts]
        return {"trades": len(ts), "wins": sum(p > 0 for p in pnl), "net": round(sum(pnl), 2),
                "net_r": round(sum(t["r"] for t in ts), 2), "worst": min(pnl) if pnl else None}

    out = {}
    for v in VARIANTS:
        ts = [(r, r[v]) for r in rows if isinstance(r[v], dict)]
        out[v] = {"all": group([t for _, t in ts]),
                  "stop: his": group([t for r, t in ts if r["invalid_from"] == "his"]),
                  "stop: atr": group([t for r, t in ts if r["invalid_from"] == "atr"]),
                  "market up at entry": group([t for _, t in ts if (t["market_pct"] or 0) >= 0]),
                  "market down at entry": group([t for _, t in ts if (t["market_pct"] or 0) < 0])}
    return out


def yahoo_bars(symbol: str) -> list[dict]:
    import yfinance as yf

    from .market import yahoo_symbol

    h = yf.Ticker(yahoo_symbol(symbol)).history(period="60d", interval="15m")
    bars = [{"start": t.to_pydatetime().astimezone(ET), "open": float(r.Open), "high": float(r.High),
             "low": float(r.Low), "close": float(r.Close), "volume": float(r.Volume)} for t, r in h.iterrows()]
    return [b for b in bars if "09:30" <= hhmm(b["start"]) <= "15:45"]


def run(account: float, since: str | None = None, until: str | None = None, setups=("downtrend-dip",),
        max_order_pct: float = 75, calls: list[dict] | None = None, fetch=yahoo_bars) -> dict:
    picked = [c for c in (calls if calls is not None else calls_mod.load())
              if c["setup"] in setups and c["direction"] == "bullish"
              and (not since or c["posted"] >= since) and (not until or c["posted"] <= until)]
    cache, rows = {}, []
    for c in picked:
        for s in (c["symbol"], MARKET):
            if s not in cache:
                try:
                    cache[s] = fetch(s)
                except Exception:
                    cache[s] = []
        row = {"symbol": c["symbol"], "posted": c.get("posted_at") or c["posted"], "level": c["level"],
               "target": c["target"], "stop": c["invalid"], "invalid_from": c.get("invalid_from", "his")}
        rows.append(row | (simulate(c, cache[c["symbol"]], cache[MARKET], account, max_order_pct)
                           if cache[c["symbol"]] else {v: "skip: no bars" for v in VARIANTS}))
    return {"calls": rows, "summary": summarize(rows),
            "note": "15-minute bars, no slippage, stop wins a bar that touches both: live results will be worse"}
