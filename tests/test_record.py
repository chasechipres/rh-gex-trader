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

    def test_tag_table(self):
        entries = [
            {"time": "2026-10-16T10:00:00", "symbol": "NVD", "action": "trade", "thesis": "[breakdown trial] lost 7700"},
            {"time": "2026-10-16T10:05:00", "symbol": "NVDL", "action": "trade", "thesis": "[leveraged trial] 2x"},
            {"time": "2026-10-16T10:10:00", "symbol": "TSLL", "action": "trade", "thesis": "[leveraged trial] 2x"},
            {"time": "2026-10-16T10:20:00", "symbol": "ASTS", "action": "trade", "thesis": "[reclaim] 40 king, stop: atr"},
            {"time": "2026-10-16T10:30:00", "symbol": "MUU", "action": "trade",
             "thesis": "[reclaim] [leveraged trial] 890, stop: his"},
            {"time": "2026-10-17T12:00:00", "symbol": "NVDL", "action": "exit", "pnl": 30.0},
            {"time": "2026-10-17T12:00:00", "symbol": "NVD", "action": "exit", "pnl": -20.0},
            {"time": "2026-10-16T15:45:00", "symbol": "ASTS", "action": "exit", "pnl": 40.0},
            {"time": "2026-10-16T15:45:00", "symbol": "MUU", "action": "exit", "pnl": -10.0},
        ]
        s = record.summarize(entries)
        rows = {t["tag"]: (t["entered"], t["closed"], t["wins"], t["pnl"]) for t in s["by_tag"]}
        self.assertEqual(rows, {"breakdown trial": (1, 1, 0, -20.0), "leveraged trial": (3, 2, 1, 20.0),
                                "reclaim": (2, 2, 1, 30.0), "reclaim, stop: atr": (1, 1, 1, 40.0),
                                "reclaim, stop: his": (1, 1, 0, -10.0)})
        self.assertIn("| leveraged trial | 3 | 2 | 1/2 (50%) | $20.00 |", record.render(s, 1400, date(2026, 10, 17)))
        self.assertNotIn("**By setup tag**", record.render(record.summarize(self.ENTRIES), 1400, date(2026, 10, 17)))

    def test_fund_types_from_the_plan(self):
        exit_ = {"symbol": "NVDL", "time": "2026-10-20T12:00:00", "action": "exit", "pnl": 10}
        plans = lambda lev: [{"symbol": "NVDL", "asset": "stock", "direction": "bullish", "leverage": lev,  # noqa: E731
                              "opened": "2026-10-16T10:00:00"}]
        self.assertEqual(record.trade_type(exit_, [], plans(2)), "lev-long")
        self.assertEqual(record.trade_type(exit_, [], plans(-2)), "inverse")
        self.assertEqual(record.trade_type(exit_, [], plans(None)), "shares")

    def test_by_type_table(self):
        s = record.summarize(self.ENTRIES, self.PLANS)
        self.assertEqual([t["type"] for t in s["by_type"]], ["shares", "call", "put", "spread", "unknown"])
        text = record.render(s, 1405.28, date(2026, 10, 14))
        self.assertIn("**By trade type**", text)
        self.assertIn("| spread | 1 | 1/1 (100%) | $40.00 |", text)
        self.assertIn("| 2026-10-09 | GME | shares | $1.16 | +1.1% |", text)

    def test_summaries_come_before_the_trade_list(self):
        text = record.render(record.summarize(self.ENTRIES, self.PLANS), 1405.28, date(2026, 10, 14))
        self.assertLess(text.index("By trade type"), text.index("By entry confidence"))
        self.assertLess(text.index("By entry confidence"), text.index("**Closed trades**"))
        self.assertNotIn("<details>", text)

    def test_long_history_folds_into_details(self):
        exits = [{"time": f"2026-10-{d:02d}T10:00:00", "symbol": f"T{d}", "action": "exit", "pnl": 1.0, "pnl_pct": 5.0}
                 for d in range(1, 15)]
        text = record.render(record.summarize(exits), 1000, date(2026, 10, 15))
        recent, folded = text.split("<details>")
        self.assertIn("**Last 10 closed trades** (newest first)", recent)
        self.assertIn("| 2026-10-14 | T14 |", recent)
        self.assertNotIn("| 2026-10-04 | T4 |", recent)
        self.assertLess(recent.index("T14"), recent.index("T13"))
        self.assertIn("<summary>All 14 closed trades</summary>", folded)
        self.assertIn("| 2026-10-01 | T1 |", folded)

    def test_no_trades_no_type_table(self):
        self.assertNotIn("By trade type", record.render(record.summarize([]), 1000, date(2026, 10, 14)))


if __name__ == "__main__":
    unittest.main()
