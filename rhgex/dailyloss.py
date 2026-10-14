"""Loss stops on new entries: a daily stop and a drawdown-from-peak pause. Exits are never blocked.

The hook records the account value on every get_portfolio call. The first value recorded on a calendar day is
that day's start_value; the daily stop compares the latest value against it (max_daily_loss_pct). The highest
value ever recorded is peak_value; the drawdown pause refuses entries once the latest value is
max_drawdown_pct below it, until the owner reviews and runs `rhgex peak reset`. A deposit made mid-day hides
losses up to its size; a withdrawal looks like a loss (the owner resets the peak after one).
private/state/account.json is local to each machine, so each machine tracks its own peak.
"""

DEFAULT_PCT = 20.0
DEFAULT_DRAWDOWN_PCT = 30.0


def record(prev: dict | None, value: float, today: str, now: str) -> dict:
    """The account record after a new value: the day's first value as start_value, the all-time high as peak."""
    start = prev.get("start_value") if prev and prev.get("date") == today else None
    peak = max(value, (prev or {}).get("peak_value") or 0)
    return {"date": today, "time": now, "total_value": value,
            "start_value": start if start is not None else value, "peak_value": peak}


def reset_peak(rec: dict) -> dict:
    """The owner's resume after a drawdown pause: today's value becomes the new peak."""
    return {**rec, "peak_value": rec["total_value"]}


def _drawdown_pct() -> float:
    try:
        from . import guardrails
        return float(guardrails.load()["limits"].get("max_drawdown_pct", DEFAULT_DRAWDOWN_PCT))
    except Exception:
        return DEFAULT_DRAWDOWN_PCT


def check(rec: dict | None, today: str, pct: float = DEFAULT_PCT,
          drawdown_pct: float | None = None) -> tuple[bool, str]:
    """(ok, reason) for a new entry. No record for today means nothing to compare; the size limits refuse it."""
    if not rec or rec.get("date") != today or not rec.get("start_value"):
        return True, "ok"
    now = rec["total_value"]
    peak = rec.get("peak_value")
    dd_limit = _drawdown_pct() if drawdown_pct is None else drawdown_pct
    if peak:
        dd = (peak - now) / peak * 100
        if dd >= dd_limit:
            return False, (f"drawdown pause: {dd:.1f}% below the peak (${peak:,.2f} -> ${now:,.2f}), limit "
                           f"{dd_limit:g}%; exits only until the owner reviews and runs `rhgex peak reset`")
    start = rec["start_value"]
    loss = (start - now) / start * 100
    if loss >= pct:
        return False, (f"daily loss stop: down {loss:.1f}% today (${start:,.2f} -> ${now:,.2f}), limit {pct:g}%; "
                       "exits only until tomorrow")
    return True, "ok"
