import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from rhgex import guardrails, hook, paper, record
from tests import template_guardrails

NOW = "2026-11-03T07:00:00"
TODAY = date(2026, 11, 3)


class Paper(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "paper.json"
        paper.start(1500, self.path, now=NOW)
        self.cfg = template_guardrails()

    def tearDown(self):
        self.dir.cleanup()

    def order(self, key, side, qty, typ="limit", limit=None, stop=None, quotes=None, plan=True):
        return paper.order(key, side, qty, typ, limit, stop, quotes or {}, path=self.path, cfg=self.cfg,
                           today=TODAY, has_plan=lambda s: plan, now=NOW)

    def test_marketable_buy_fills_at_the_ask_and_moves_cash(self):
        r = self.order("CRWV", "buy", 10, limit=53.10, quotes={"CRWV": (53.00, 53.05)})
        self.assertEqual(r["fill"]["price"], 53.05)
        st = paper.load(self.path)
        self.assertEqual(st["cash"], 1500 - 530.5)
        self.assertEqual(st["positions"]["CRWV"]["qty"], 10)

    def test_share_limit_below_the_ask_rests_until_the_ask_comes_down(self):
        r = self.order("CRWV", "buy", 10, limit=52.90, quotes={"CRWV": (52.85, 53.00)})
        self.assertNotIn("fill", r)
        out = paper.check({"CRWV": (52.80, 52.88)}, path=self.path, now=NOW)
        self.assertEqual(out["fills"][0]["price"], 52.88)

    def test_option_limit_at_the_mid_fills_at_the_limit(self):
        key = "NVDA 2026-11-20 200C"
        r = self.order(key, "buy", 1, limit=1.15, quotes={key: (1.10, 1.20)})
        self.assertEqual(r["fill"]["price"], 1.15)
        self.assertEqual(paper.load(self.path)["cash"], 1500 - 115)

    def test_no_plan_refuses_an_entry(self):
        r = self.order("CRWV", "buy", 1, limit=53, quotes={"CRWV": (52.9, 53)}, plan=False)
        self.assertIn("no exit plan", r["refused"])

    def test_guardrails_apply_blocked_and_size(self):
        self.cfg["blocked"] = [{"name": "test", "symbols": ["SPY"], "until": ""}]
        self.assertIn("blocked", self.order("SPY", "buy", 1, limit=600, plan=True)["refused"])
        # 75% of $1,500 is the template's stock order cap
        self.assertIn("exceeds", self.order("CRWV", "buy", 30, limit=53)["refused"])

    def test_sell_is_reserved_by_the_resting_stop(self):
        self.order("CRWV", "buy", 10, limit=53.10, quotes={"CRWV": (53.00, 53.05)})
        self.order("CRWV", "sell", 10, "stop_market", stop=49.61)
        with self.assertRaises(ValueError):
            self.order("CRWV", "sell", 10, limit=54)
        paper.cancel("CRWV", path=self.path)
        r = self.order("CRWV", "sell", 10, limit=54, quotes={"CRWV": (54.1, 54.2)})
        self.assertEqual(r["fill"]["pnl"], round((54.1 - 53.05) * 10, 2))
        self.assertIn("position_closed", r["fill"])

    def test_stop_touched_by_a_low_fills_at_the_stop(self):
        self.order("CRWV", "buy", 10, limit=53.10, quotes={"CRWV": (53.00, 53.05)})
        self.order("CRWV", "sell", 10, "stop_market", stop=49.61)
        out = paper.check({"CRWV": (50.10, 50.15)}, path=self.path, lows=lambda s, t: 49.50, now=NOW)
        self.assertEqual(out["fills"][0]["price"], 49.61)

    def test_gap_through_the_stop_fills_at_the_bid(self):
        self.order("CRWV", "buy", 10, limit=53.10, quotes={"CRWV": (53.00, 53.05)})
        self.order("CRWV", "sell", 10, "stop_market", stop=49.61)
        out = paper.check({"CRWV": (47.00, 47.05)}, path=self.path, now=NOW)
        self.assertEqual(out["fills"][0]["price"], 47.00)
        self.assertEqual(out["value"], round(1500 - 530.5 + 470, 2))

    def test_stop_limit_can_get_stuck(self):
        key = "NVDA 2026-11-20 200C"
        self.order(key, "buy", 1, limit=1.15, quotes={key: (1.10, 1.20)})
        self.order(key, "sell", 1, "stop_limit", limit=0.65, stop=0.75)
        out = paper.check({key: (0.50, 0.60)}, path=self.path, now=NOW)
        self.assertEqual(out["fills"], [])
        self.assertEqual(len(out["stuck_stops"]), 1)

    def test_daily_loss_stop_refuses_new_entries(self):
        self.order("CRWV", "buy", 20, limit=53.10, quotes={"CRWV": (53.00, 53.05)})
        r = self.order("NVDA", "buy", 1, limit=200, quotes={"CRWV": (30.0, 30.1), "NVDA": (199.9, 200)})
        self.assertRegex(r["refused"], "daily loss stop|drawdown pause")

    def test_hook_refuses_real_orders_while_paper_is_on(self):
        event = {"tool_name": "mcp__robinhood-trading__place_equity_order",
                 "tool_input": {"account_number": "X", "symbol": "NKE", "side": "sell", "type": "limit",
                                "quantity": "1", "limit_price": "34"}}
        with mock.patch.object(paper, "PAPER", self.path), mock.patch.object(guardrails, "load", template_guardrails):
            buf = io.StringIO()
            with redirect_stdout(buf):
                hook.pre(event)
        out = json.loads(buf.getvalue())["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("paper trading", out["permissionDecisionReason"])

    def test_record_renders_the_paper_block(self):
        st = paper.summary(paper.load(self.path))
        text = record.render(record.summarize([]), st["value"], paper=st)
        self.assertIn("Paper trades (from 2026-11-03, $1,500.00 start)", text)
        self.assertIn("+0.00%", text)


if __name__ == "__main__":
    unittest.main()
