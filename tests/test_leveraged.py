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
        self.assertEqual(leveraged.funds_for("nvda"), ["NVD", "NVDD", "NVDL", "NVDQ"])

    def test_fund_level_doubles_the_move(self):
        # stock 100 -> 95 (-5%) is -10% on a 2x fund at 40
        self.assertEqual(leveraged.fund_level(40, 100, 95, 2), 36.0)
        self.assertEqual(leveraged.fund_level(40, 100, 110, 2), 48.0)

    def test_inverse_fund_moves_against_the_stock(self):
        self.assertEqual(leveraged.underlying("NVD"), ("NVDA", -2))
        self.assertEqual(leveraged.fund_level(10, 100, 105, -2), 9.0)  # stock +5%: inverse fund -10%
        self.assertEqual(sorted(leveraged.funds_for("TSLA")), ["TSLL", "TSLQ", "TSLS", "TSLZ"])


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
        self.assertEqual(rep[0]["price_source"], "passed")
        # NVDA 211 vs the 212 stop: NVDL at 30 maps the stop to 30 x (1 + 2 x (212/211 - 1)) = 30.28
        self.assertEqual(rep[0]["fund_stop"], 30.28)
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

    def test_at_most_two_funds_open(self):
        trade = dict(symbol="NVDL", direction="bullish", price=218, stop=212, target=230, asset="stock", legs=[])
        funds = [{"symbol": s, "leverage": 2, "direction": "bullish", "stop": 1, "price": 2} for s in ("TSLL", "AMDL")]
        ok = lambda plans: {x["check"]: x["ok"] for x in preflight.evaluate(good(**trade), ctx(plans=plans))}  # noqa: E731
        self.assertTrue(ok(funds[:1])["open_funds"])
        self.assertFalse(ok(funds)["open_funds"])

    def test_fund_liquidity(self):
        # NVDA 218, stop 212 (-2.75%): a 2x fund at 33 has its stop ~1.82 away, so the spread may be up to ~0.09
        trade = dict(symbol="NVDL", direction="bullish", price=218, stop=212, target=230, asset="stock", legs=[])
        busy = ctx(dollar_volume=lambda s: 80e6)
        check = lambda c, q: {x["check"]: x["ok"] for x in preflight.evaluate(good(quote=q, **trade), c)}  # noqa: E731
        self.assertTrue(check(busy, (32.99, 33.01))["fund_liquidity"])
        self.assertFalse(check(busy, (32.80, 33.20))["fund_liquidity"])              # spread 22% of the risk
        self.assertFalse(check(ctx(dollar_volume=lambda s: 1e6), (32.99, 33.01))["fund_liquidity"])  # thin
        self.assertFalse(check(busy, None)["fund_liquidity"])                       # no live quote

    def test_fund_direction_must_match(self):
        bull = dict(direction="bullish", price=218, stop=212, target=230, asset="stock", legs=[])
        bear = dict(direction="bearish", price=218, stop=224, target=206, asset="stock", legs=[])
        self.assertNotIn("fund_direction", failed(preflight.evaluate(good(symbol="NVDL", **bull), ctx())))
        self.assertIn("fund_direction", failed(preflight.evaluate(good(symbol="NVD", **bull), ctx())))
        self.assertNotIn("fund_direction", failed(preflight.evaluate(good(symbol="NVD", **bear), ctx())))


if __name__ == "__main__":
    unittest.main()
