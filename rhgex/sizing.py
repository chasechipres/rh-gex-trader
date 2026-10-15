"""Position sizing: how much to buy so a full loss costs a fixed share of the account.

Risk is what's lost if the trade fails: the premium for a long option or debit spread (it can go to zero), and
(entry - stop) per share for stock. Both get the same budget.
"""

import math

OPTION_RISK_PCT = 5.0  # premium (or spread max loss) per trade, % of account
SHARE_RISK_PCT = 5.0   # (entry - stop) x shares per trade, % of account (a gap through the stop can exceed it)


def option_contracts(account: float, cost_per_contract: float, pct: float = OPTION_RISK_PCT) -> dict:
    """cost_per_contract: max loss per contract in dollars (premium x 100, or debit x 100 for a spread)."""
    if cost_per_contract <= 0:
        raise ValueError("cost per contract must be positive")
    budget = account * pct / 100
    n = math.floor(budget / cost_per_contract)
    return {"risk_pct": pct, "risk_budget": round(budget, 2), "contracts": n, "risk": round(n * cost_per_contract, 2),
            "fits": n >= 1}


def shares(account: float, entry: float, stop: float, pct: float = SHARE_RISK_PCT,
           max_cost: float | None = None) -> dict:
    """max_cost: the hook's per-order dollar cap; when the risk-sized order would cost more, fewer shares."""
    per_share = abs(entry - stop)
    if per_share <= 0:
        raise ValueError("entry and stop must differ")
    budget = account * pct / 100
    n = math.floor(budget / per_share)
    out = {"risk_pct": pct, "risk_budget": round(budget, 2)}
    if max_cost is not None and n * entry > max_cost:
        n = math.floor(max_cost / entry)
        out["capped_by"] = f"max order ${max_cost:g}"
    return {**out, "shares": n, "risk": round(n * per_share, 2), "cost": round(n * entry, 2), "fits": n >= 1}
