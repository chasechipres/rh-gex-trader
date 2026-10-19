import tempfile
import unittest
from datetime import date
from pathlib import Path

from rhgex import exits

TODAY = date(2026, 10, 8)


class Plans(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "plans.json"

    def test_add_close_cycle(self):
        exits.add("arm", "stock", "bullish", 291, 325, "reclaim 300", path=self.path, price=300)
        self.assertTrue(exits.has_open_plan("ARM", self.path))
        with self.assertRaises(ValueError):  # one open plan per symbol
            exits.add("ARM", "stock", "bullish", 291, 325, "dup", path=self.path, price=300)
        exits.close("ARM", "target hit", path=self.path)
        self.assertFalse(exits.has_open_plan("ARM", self.path))

    def test_validation(self):
        with self.assertRaises(ValueError):
            exits.add("ARM", "stock", "bullish", 330, 300, "stop above target", path=self.path)
        with self.assertRaises(ValueError):
            exits.add("NKE", "option", "bearish", 32, 36, "put with stop below target", "2026-10-30", path=self.path)
        with self.assertRaises(ValueError):
            exits.add("NKE", "option", "bearish", 36, 32, "no expiry", path=self.path)

    def test_reward_risk(self):
        with self.assertRaises(ValueError):  # no price
            exits.add("ARM", "stock", "bullish", 291, 325, "", path=self.path)
        with self.assertRaises(ValueError):  # (325 - 312) / (312 - 291) = 0.62
            exits.add("ARM", "stock", "bullish", 291, 325, "", path=self.path, price=312)
        with self.assertRaises(ValueError):  # price already past the target
            exits.add("ARM", "stock", "bullish", 291, 325, "", path=self.path, price=330)
        with self.assertRaises(ValueError):  # put: (34 - 32.5) / (35.8 - 34) = 0.83
            exits.add("NKE", "option", "bearish", 35.8, 32.5, "", "2026-10-30", path=self.path, price=34)
        plan = exits.add("ARM", "stock", "bullish", 291, 325, "", path=self.path, price=304.6)
        self.assertEqual(plan["reward_risk"], 1.5)

    def test_entry_cap(self):
        self.assertEqual(exits.entry_cap("bullish", 291, 325), 304.6)  # (325 + 1.5 * 291) / 2.5
        self.assertEqual(exits.reward_risk("bullish", 304.6, 291, 325), 1.5)
        self.assertEqual(exits.entry_cap("bearish", 35.8, 32.5), 34.48)  # lowest put/inverse entry
        self.assertEqual(exits.reward_risk("bearish", 34.48, 35.8, 32.5), 1.5)

    def test_existing_skips_reward_risk(self):
        plan = exits.add("ARM", "stock", "bullish", 291, 325, "held", path=self.path, price=320, existing=True)
        self.assertIsNone(plan["reward_risk"])
        self.assertTrue(plan["existing"])

    def test_check_uses_price_overrides(self):
        exits.add("ARM", "stock", "bullish", 291, 325, "", path=self.path, price=300)
        exits.add("NKE", "option", "bearish", 35.8, 32.5, "", "2026-10-09", path=self.path, price=34.5)
        report = {r["symbol"]: r["signals"] for r in exits.check({"ARM": 300, "NKE": 32.0}, TODAY, self.path,
                                                                 earnings=lambda s: None)}
        self.assertEqual(report["ARM"], ["HOLD"])
        self.assertEqual(report["NKE"], ["TARGET_HIT", "EXPIRING"])


class Evaluate(unittest.TestCase):
    bull = {"direction": "bullish", "stop": 291, "target": 325, "asset": "stock", "expiration": None}
    bear = {"direction": "bearish", "stop": 35.8, "target": 32.5, "asset": "option", "expiration": "2026-10-30"}

    def test_bullish(self):
        self.assertEqual(exits.evaluate(self.bull, 290, TODAY), ["STOP_HIT"])
        self.assertEqual(exits.evaluate(self.bull, 326, TODAY), ["TARGET_HIT"])
        self.assertEqual(exits.evaluate(self.bull, 300, TODAY), [])

    def test_bearish(self):
        self.assertEqual(exits.evaluate(self.bear, 36, TODAY), ["STOP_HIT"])
        self.assertEqual(exits.evaluate(self.bear, 32, TODAY), ["TARGET_HIT"])

    def test_expiring_and_no_price(self):
        self.assertEqual(exits.evaluate(self.bear, 34, date(2026, 10, 28)), ["EXPIRING"])
        self.assertEqual(exits.evaluate(self.bull, None, TODAY), ["NO_PRICE"])

    def test_earnings_soon(self):
        wed = date(2026, 10, 14)
        self.assertIn("EARNINGS_SOON", exits.evaluate(self.bull, 300, wed, earnings=date(2026, 10, 19)))  # Mon: 3
        self.assertEqual(exits.evaluate(self.bull, 300, wed, earnings=date(2026, 10, 20)), [])            # Tue: 4
        self.assertIn("EARNINGS_SOON", exits.evaluate(self.bull, 300, wed, earnings=wed))                 # today
        self.assertEqual(exits.evaluate(self.bull, 300, wed, earnings=date(2026, 10, 13)), [])            # past

    def test_time_stop_for_shares(self):
        xyz = {"direction": "bullish", "stop": 90, "target": 120, "price": 100, "asset": "stock",
               "expiration": None, "opened": "2026-10-13T11:16:00"}
        self.assertEqual(exits.evaluate(xyz, 105, date(2026, 10, 26)), [])                 # 9 trading days
        self.assertEqual(exits.evaluate(xyz, 105, date(2026, 10, 27)), ["TIME_STOP"])      # 10
        self.assertEqual(exits.evaluate({**xyz, "stop": 100}, 105, date(2026, 10, 27)), [])  # reached 1R
        self.assertEqual(exits.evaluate({**xyz, "asset": "option", "expiration": "2026-11-20"}, 105,
                                        date(2026, 10, 27)), [])                            # options have expiry

    def test_at_one_r(self):
        xyz = {"direction": "bullish", "stop": 90, "target": 120, "price": 100, "asset": "stock", "expiration": None}
        self.assertEqual(exits.evaluate(xyz, 109.9, TODAY), [])          # 1R = 110
        self.assertEqual(exits.evaluate(xyz, 110, TODAY), ["AT_1R"])
        self.assertEqual(exits.evaluate({**xyz, "stop": 100, "initial_stop": 90}, 112, TODAY), [])  # at breakeven
        put = {**self.bear, "price": 34.0}                             # risk 1.8 -> 1R at 32.2, below target
        self.assertEqual(exits.evaluate({**put, "target": 30}, 32.2, TODAY), ["AT_1R"])
        self.assertEqual(exits.evaluate({**xyz, "price": None}, 115, TODAY), [])  # rebuilt plan: no entry price


class RaiseStop(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "plans.json"

    def test_only_tightens(self):
        exits.add("XYZ", "stock", "bullish", 90, 120, "", path=self.path, price=100)
        p = exits.raise_stop("xyz", 100, path=self.path)
        self.assertEqual((p["stop"], p["initial_stop"]), (100, 90))
        with self.assertRaises(ValueError):
            exits.raise_stop("XYZ", 95, path=self.path)
        self.assertEqual(exits.raise_stop("XYZ", 105, path=self.path)["initial_stop"], 90)

    def test_bearish_moves_down(self):
        exits.add("NKE", "option", "bearish", 35.8, 30, "", "2026-10-30", path=self.path, price=34)
        self.assertEqual(exits.raise_stop("NKE", 34, path=self.path)["stop"], 34)
        with self.assertRaises(ValueError):
            exits.raise_stop("NKE", 35, path=self.path)

    def test_no_plan(self):
        with self.assertRaises(ValueError):
            exits.raise_stop("ARM", 300, path=self.path)


class HookRequiresPlan(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        self.path = Path(tempfile.mkdtemp()) / "plans.json"
        patcher = mock.patch.object(exits, "PLANS", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        from rhgex import hook
        self.has_entry_plan = exits.has_entry_plan
        mock.patch.object(exits, "has_entry_plan", lambda s, path=None: self.has_entry_plan(s, self.path)).start()
        self.value = 115.22
        mock.patch.object(hook, "account_value", lambda acct: self.value).start()
        mock.patch.object(hook, "ledger_today", lambda: []).start()  # isolate from today's real orders
        from rhgex import guardrails
        from tests import template_guardrails
        mock.patch.object(guardrails, "load", template_guardrails).start()
        self.addCleanup(mock.patch.stopall)

    def decide(self, side):
        import io, json
        from contextlib import redirect_stdout
        from rhgex import hook
        event = {"tool_name": "mcp__robinhood-trading__place_equity_order",
                 "tool_input": {"account_number": "X", "symbol": "NKE", "side": side, "type": "limit",
                                "quantity": "1", "limit_price": "34"}}
        buf = io.StringIO()
        with redirect_stdout(buf):
            hook.pre(event)
        return json.loads(buf.getvalue())["hookSpecificOutput"]

    def test_entry_without_plan_denied(self):
        out = self.decide("buy")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("no exit plan", out["permissionDecisionReason"])

    def test_entry_with_plan_allowed(self):
        exits.add("NKE", "stock", "bullish", 32, 38, "", path=self.path, price=34)
        self.assertEqual(self.decide("buy")["permissionDecision"], "allow")

    def test_existing_plan_allows_no_entry(self):
        exits.add("NKE", "stock", "bullish", 32, 38, "held", path=self.path, existing=True)
        out = self.decide("buy")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("--existing", out["permissionDecisionReason"])

    def test_entry_without_account_value_denied(self):
        exits.add("NKE", "stock", "bullish", 32, 38, "", path=self.path, price=34)
        self.value = None
        out = self.decide("buy")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("get_portfolio", out["permissionDecisionReason"])

    def test_exit_needs_no_plan(self):
        self.assertEqual(self.decide("sell")["permissionDecision"], "allow")

    def test_exit_needs_no_account_value(self):
        self.value = None
        self.assertEqual(self.decide("sell")["permissionDecision"], "allow")


if __name__ == "__main__":
    unittest.main()
