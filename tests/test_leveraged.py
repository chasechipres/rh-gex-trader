import tempfile
import unittest
from datetime import date
from pathlib import Path

from rhgex import exits, guardrails, hook, leveraged, preflight

from tests.test_guardrails import CFG, TODAY
from tests.test_preflight import ctx, failed, good


class FundMath(unittest.TestCase):
    def test_lookup(self):
        self.assertEqual(leveraged.underlying("nvdl"), ("NVDA", 2))
        self.assertIsNone(leveraged.underlying("NVDA"))
        self.assertEqual(leveraged.funds_for("nvda"), ["NVDL"])

    def test_fund_level_doubles_the_move(self):
        # stock 100 -> 95 (-5%) is -10% on a 2x fund at 40
        self.assertEqual(leveraged.fund_level(40, 100, 95, 2), 36.0)
        self.assertEqual(leveraged.fund_level(40, 100, 110, 2), 48.0)


class HookBlocksTheFund(unittest.TestCase):
    def test_fund_on_a_blocked_stock_is_refused(self):
        cfg = {**CFG, "blocked": [{"name": "held", "symbols": ["NVDA"], "until": ""}]}
        order = hook.normalize("mcp__robinhood-trading__place_equity_order",
                               {"account_number": "X", "symbol": "NVDL", "side": "buy", "type": "limit",
                                "quantity": "1", "limit_price": "33"})
        ok, why = guardrails.check(cfg, order, [], TODAY)
        self.assertFalse(ok)
        self.assertIn("NVDA", why)


class FundPlans(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "plans.json"
        exits.add("NVDL", "stock", "bullish", 212, 230, "NVDA reclaim", path=self.path, price=218)

    def test_plan_records_the_stock(self):
        p = exits.load(self.path)[0]
        self.assertEqual((p["underlying"], p["leverage"]), ("NVDA", 2))

    def test_exit_check_quotes_the_stock(self):
        seen = []
        rep = exits.check({"NVDA": 211, "NVDL": 30}, today=date(2026, 10, 16), path=self.path,
                          earnings=lambda s: seen.append(s))
        self.assertEqual(rep[0]["price"], 211)
        self.assertIn("STOP_HIT", rep[0]["signals"])
        self.assertEqual(seen, ["NVDA"])

    def test_shorter_time_stop(self):
        p = {**exits.load(self.path)[0], "opened": "2026-10-08T10:00:00"}
        self.assertTrue(exits.time_stop(p, date(2026, 10, 15)))           # 5 trading days
        self.assertFalse(exits.time_stop({**p, "leverage": None}, date(2026, 10, 15)))  # plain shares: 10


class FundPreflight(unittest.TestCase):
    def test_checked_on_the_stock(self):
        seen = []
        c = ctx(earnings=lambda s: seen.append(s), blocks={"NVDA": "held"})
        checks = preflight.evaluate(good(symbol="NVDL", asset="stock", legs=[]), c)
        self.assertIn("blocked", failed(checks))
        self.assertIn("leverage", {ch["check"] for ch in checks})
        self.assertEqual(seen, ["NVDA"])


if __name__ == "__main__":
    unittest.main()
