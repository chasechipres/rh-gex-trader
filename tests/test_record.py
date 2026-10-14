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
        self.assertIn("| 2026-10-09 | KTOS | $-6.50 | -40.0% |", text)
        self.assertTrue(text.endswith("## Next\n"))


if __name__ == "__main__":
    unittest.main()
