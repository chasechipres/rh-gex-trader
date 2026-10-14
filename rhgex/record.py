"""Track record: realized P/L from closed trades (`journal exit --pnl`), split by the entry's confidence and by
trade type (shares, call, put or spread).

`rhgex record --readme` rewrites the block between the track-record markers in private/README.md.
"""

import json
import re
from datetime import date
from pathlib import Path

from . import paths

JOURNAL = paths.LOGS / "journal.jsonl"
README = paths.README
START, END = "<!-- track-record:start -->", "<!-- track-record:end -->"


def load(path: Path = JOURNAL) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


BANDS = [("low (<0.4)", 0.0, 0.4), ("mid (0.4-0.6)", 0.4, 0.6), ("high (>=0.6)", 0.6, 1.01)]


TYPES = ["shares", "call", "put", "spread"]


def _entry_trade(exit_entry: dict, entries: list[dict]) -> dict | None:
    """The latest `trade` entry for the same symbol before this exit."""
    trades = [e for e in entries if e["action"] == "trade" and e["symbol"] == exit_entry["symbol"]
              and e["time"] <= exit_entry["time"]]
    return trades[-1] if trades else None


def entry_confidence(exit_entry: dict, entries: list[dict]) -> float | None:
    trade = _entry_trade(exit_entry, entries)
    return trade.get("confidence") if trade else None


def trade_type(exit_entry: dict, entries: list[dict], plans: list[dict] = ()) -> str:
    """The entry's `journal trade --type`; for older entries without one, the latest plan for the symbol opened
    before the exit (stock -> shares; option -> call if bullish, put if bearish: it can't tell a spread)."""
    trade = _entry_trade(exit_entry, entries)
    if trade and trade.get("type") in TYPES:
        return trade["type"]
    opened = [p for p in plans if p.get("symbol") == exit_entry["symbol"]
              and p.get("opened", "") <= exit_entry["time"]]
    if not opened:
        return "unknown"
    plan = opened[-1]
    if plan.get("asset") == "stock":
        return "shares"
    return {"bullish": "call", "bearish": "put"}.get(plan.get("direction"), "unknown")


def _group(trades: list[dict]) -> dict:
    return {"closed": len(trades), "wins": sum(1 for e in trades if e["pnl"] > 0),
            "pnl": round(sum(e["pnl"] for e in trades), 2)}


def summarize(entries: list[dict], plans: list[dict] = ()) -> dict:
    live = [{**e, "entry_confidence": entry_confidence(e, entries), "type": trade_type(e, entries, plans)}
            for e in entries if e["action"] == "exit" and e.get("pnl") is not None]
    bands = []
    for label, lo, hi in BANDS:
        b = [e for e in live if e["entry_confidence"] is not None and lo <= e["entry_confidence"] < hi]
        bands.append({"band": label, **_group(b)})
    types = [{"type": t, **_group([e for e in live if e["type"] == t])}
             for t in TYPES + ["unknown"] if any(e["type"] == t for e in live)]
    return {"live": {"trades": live, "closed": len(live), "wins": sum(1 for e in live if e["pnl"] > 0),
                     "realized_pnl": round(sum(e["pnl"] for e in live), 2)},
            "by_confidence": bands, "by_type": types}


def _rate(wins: int, n: int) -> str:
    return f"{wins}/{n} ({wins / n:.0%})" if n else "n/a"


def render(s: dict, account_value: float | None = None, today: date | None = None) -> str:
    today = today or date.today()
    live = s["live"]
    lines = [f"_Updated {today.isoformat()} by `rhgex record --readme`._", "",
             "**Live trades (agentic account)**", "",
             "| Account value | Closed trades | Win rate | Realized P/L |", "|---|---|---|---|",
             f"| {f'${account_value:,.2f}' if account_value is not None else 'n/a'} | {live['closed']} | "
             f"{_rate(live['wins'], live['closed'])} | ${live['realized_pnl']:,.2f} |", ""]
    if live["trades"]:
        lines += ["| Closed | Ticker | Type | P/L | P/L % |", "|---|---|---|---|---|"]
        for e in live["trades"]:
            pct = "n/a" if e.get("pnl_pct") is None else f"{e['pnl_pct']:+.1f}%"
            kind = e.get("type", "unknown")
            lines.append(f"| {e['time'][:10]} | {e['symbol']} | {kind} | ${e['pnl']:,.2f} | {pct} |")
        lines.append("")
    if s.get("by_type"):
        lines += ["**By trade type**", "", "| Type | Closed | Win rate | P/L |", "|---|---|---|---|"]
        for t in s["by_type"]:
            lines.append(f"| {t['type']} | {t['closed']} | {_rate(t['wins'], t['closed'])} | ${t['pnl']:,.2f} |")
        lines.append("")
    if any(b["closed"] for b in s.get("by_confidence", [])):
        lines += ["**By entry confidence**", "", "| Confidence | Closed | Win rate | P/L |", "|---|---|---|---|"]
        for b in s["by_confidence"]:
            lines.append(f"| {b['band']} | {b['closed']} | {_rate(b['wins'], b['closed'])} | ${b['pnl']:,.2f} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def write_readme(block: str, path: Path = README) -> None:
    text = path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise ValueError(f"README has no {START} ... {END} block")
    text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: f"{START}\n{block}\n{END}", text,
                  flags=re.S)
    path.write_text(text, encoding="utf-8")
