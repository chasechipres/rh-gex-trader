import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest import mock

from rhgex import guardrails, hook
from tests import template_guardrails


class HookDailyLoss(unittest.TestCase):
    def decide(self, side, start, now):
        rec = {"date": date.today().isoformat(), "total_value": now, "start_value": start}
        event = {"tool_name": "mcp__robinhood-trading__place_equity_order",
                 "tool_input": {"account_number": "X", "symbol": "NKE", "side": side, "type": "limit",
                                "quantity": "1", "limit_price": "34"}}
        with mock.patch.object(guardrails, "load", template_guardrails), \
                mock.patch.object(hook, "account_value", lambda a: now), \
                mock.patch.object(hook, "account_record", lambda a: rec), \
                mock.patch.object(hook, "ledger_today", lambda: []), \
                mock.patch.object(hook.exits, "has_entry_plan", lambda s, path=None: True):
            buf = io.StringIO()
            with redirect_stdout(buf):
                hook.pre(event)
        return json.loads(buf.getvalue())["hookSpecificOutput"]

    def test_entry_allowed_under_the_loss_limit(self):
        self.assertEqual(self.decide("buy", 1000, 900)["permissionDecision"], "allow")

    def test_entry_denied_at_the_loss_limit(self):
        out = self.decide("buy", 1000, 800)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("daily loss stop", out["permissionDecisionReason"])

    def test_exit_still_allowed_when_down(self):
        self.assertEqual(self.decide("sell", 1000, 500)["permissionDecision"], "allow")
