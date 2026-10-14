"""Wash-sale log (private/logs/wash_sales.jsonl): a record of loss exits and their 30-day windows. Logging only.

Robinhood's 1099-B flags wash sales only for the same security re-bought in the same account. This log covers
what it misses: re-entries through options on the same underlying, a different strike or expiry, and buys of
the symbol in the user's other accounts. Nothing here refuses an order; `blocks` and `research` show the open
windows as warnings, and the entries are a record for tax time.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import paths

LOG = paths.LOGS / "wash_sales.jsonl"
WINDOW_DAYS = 30  # a buy within 30 days before or after a loss sale can wash it


def load(path: Path = LOG) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def add(symbol: str, loss: float, sold: str | None = None, asset: str = "stock", contract: str = "",
        note: str = "", path: Path = LOG) -> dict:
    """Record a closing sale at a loss. loss is the realized loss in dollars (positive number)."""
    if loss <= 0:
        raise ValueError("loss must be a positive dollar amount; gains don't start a wash-sale window")
    if asset not in ("stock", "option"):
        raise ValueError("asset must be stock or option")
    sold_on = date.fromisoformat(sold) if sold else date.today()
    entry = {"symbol": symbol.upper().lstrip("$"), "asset": asset, "contract": contract, "loss": round(loss, 2),
             "sold": sold_on.isoformat(), "window_start": (sold_on - timedelta(days=WINDOW_DAYS)).isoformat(),
             "window_end": (sold_on + timedelta(days=WINDOW_DAYS)).isoformat(), "note": note,
             "logged": datetime.now().isoformat(timespec="seconds")}
    paths.ensure(path.parent)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def active(today: date | None = None, path: Path = LOG) -> list[dict]:
    """Loss exits whose window hasn't ended: re-buying the symbol (or options on it) before window_end washes them."""
    today = today or date.today()
    return [e for e in load(path) if date.fromisoformat(e["window_end"]) >= today]


def warnings(today: date | None = None, path: Path = LOG) -> dict[str, str]:
    """symbol -> one-line warning, for each symbol with an open window."""
    out = {}
    for e in sorted(active(today, path), key=lambda e: e["window_end"]):  # the latest window wins
        out[e["symbol"]] = (f"loss ${e['loss']:.2f} sold {e['sold']}; re-buying {e['symbol']} or its options "
                            f"through {e['window_end']} may wash it")
    return out
