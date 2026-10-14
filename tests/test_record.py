import tempfile
import unittest
from datetime import date
from pathlib import Path

from rhgex import record


class Summary(unittest.TestCase):
    ENTRIES = [
        {"time": "2026-10-08T09:00:00", "symbol": "ARM", "action": "skip"},
        {"time": "2026-10-09T12:00:00", "symbol": "KTOS", "action": "exit", "pnl": -6.5, "pnl_pct": -40.0},
        {"time": "2026-10-10T12:00:00", "symbol": "NKE", "action": "exit", "pnl": 12.0, "pnl_pct": 60.0},
        {"time": "2026-10-11T12:00:00", "symbol": "XYZ", "action": "exit"},  # no --pnl: not counted
    ]

    def test_win_rate_by_entry_confidence(self):
        entries = [
            {"time": "2026-10-08T09:00:00", "symbol": "KTOS", "action": "trade", "confidence": 0.3},
            {"time": "2026-10-08T10:00:00", "symbol": "NKE", "action": "trade", "confidence": 0.55},
        ] + self.ENTRIES
        bands = {b["band"]: b for b in record.summarize(entries)["by_confidence"]}
        self.assertEqual((bands["low (<0.4)"]["closed"], bands["low (<0.4)"]["wins"]), (1, 0))
        self.assertEqual((bands["mid (0.4-0.6)"]["closed"], bands["mid (0.4-0.6)"]["pnl"]), (1, 12.0))
        self.assertEqual(bands["high (>=0.6)"]["closed"], 0)
        text = record.render(record.summarize(entries), 1000, date(2026, 10, 12))
        self.assertIn("| mid (0.4-0.6) | 1 | 1/1 (100%) | $12.00 |", text)

    def test_counts_closed_trades_with_pnl(self):
        s = record.summarize(self.ENTRIES)
        self.assertEqual((s["live"]["closed"], s["live"]["wins"], s["live"]["realized_pnl"]), (2, 1, 5.5))

    def test_readme_block_rewritten(self):
        path = Path(tempfile.mkdtemp()) / "README.md"
        path.write_text(f"# x\n\n{record.START}\nold\n{record.END}\n\n## Next\n", encoding="utf-8")
        record.write_readme(record.render(record.summarize(self.ENTRIES), 115.22, date(2026, 10, 12)), path)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("old", text)
        self.assertIn("| $115.22 | 2 | 1/2 (50%) | $5.50 |", text)
        self.assertIn("| 2026-10-09 | KTOS | unknown | $-6.50 | -40.0% |", text)
        self.assertTrue(text.endswith("## Next\n"))


class TradeType(unittest.TestCase):
    ENTRIES = [
        {"time": "2026-10-08T10:00:00", "symbol": "NVDA", "action": "trade", "confidence": 0.6, "type": "spread"},
        {"time": "2026-10-09T10:00:00", "symbol": "NVDA", "action": "exit", "pnl": 40.0, "pnl_pct": 80.0},
        {"time": "2026-10-08T11:00:00", "symbol": "GME", "action": "trade", "confidence": 0.55},  # before --type
        {"time": "2026-10-09T11:00:00", "symbol": "GME", "action": "exit", "pnl": 1.16, "pnl_pct": 1.1},
        {"time": "2026-10-09T12:00:00", "symbol": "KTOS", "action": "exit", "pnl": -6.5, "pnl_pct": -40.0},
        {"time": "2026-10-09T13:00:00", "symbol": "TSLA", "action": "exit", "pnl": -10.0, "pnl_pct": -50.0},
        {"time": "2026-10-09T14:00:00", "symbol": "SOFI", "action": "exit", "pnl": 5.0, "pnl_pct": 25.0},
    ]
    PLANS = [
        {"symbol": "GME", "asset": "stock", "direction": "bullish", "opened": "2026-10-08T10:55:00"},
        {"symbol": "TSLA", "asset": "option", "direction": "bearish", "opened": "2026-10-08T09:00:00"},
        {"symbol": "SOFI", "asset": "option", "direction": "bullish", "opened": "2026-10-08T09:00:00"},
        {"symbol": "SOFI", "asset": "stock", "direction": "bullish", "opened": "2026-10-10T09:00:00"},  # later trade
    ]

    def test_type_from_journal_then_plan(self):
        types = {e["symbol"]: e["type"] for e in record.summarize(self.ENTRIES, self.PLANS)["live"]["trades"]}
        self.assertEqual(types, {"NVDA": "spread", "GME": "shares", "KTOS": "unknown", "TSLA": "put",
                                 "SOFI": "call"})

    def test_by_type_table(self):
        s = record.summarize(self.ENTRIES, self.PLANS)
        self.assertEqual([t["type"] for t in s["by_type"]], ["shares", "call", "put", "spread", "unknown"])
        text = record.render(s, 1405.28, date(2026, 10, 14))
        self.assertIn("**By trade type**", text)
        self.assertIn("| spread | 1 | 1/1 (100%) | $40.00 |", text)
        self.assertIn("| 2026-10-09 | GME | shares | $1.16 | +1.1% |", text)

    def test_no_trades_no_type_table(self):
        self.assertNotIn("By trade type", record.render(record.summarize([]), 1000, date(2026, 10, 14)))


if __name__ == "__main__":
    unittest.main()
