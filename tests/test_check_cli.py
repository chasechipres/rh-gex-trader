import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from rhgex import cmd_check, exits, guardrails, hook
from tests import template_guardrails


class CheckRunsTheHook(unittest.TestCase):
    """`rhgex check` must give the same answer as the PreToolUse hook, including the exit-plan check."""

    def run_check(self, has_plan):
        order = {"account_number": "X", "symbol": "NKE", "side": "buy", "type": "limit", "quantity": "1",
                 "limit_price": "34"}
        args = SimpleNamespace(tool="place_equity_order", order_json=json.dumps(order))
        buf = io.StringIO()
        with mock.patch.object(guardrails, "load", template_guardrails), \
                mock.patch.object(hook, "account_value", lambda a: 1000.0), \
                mock.patch.object(hook, "account_record", lambda a: None), \
                mock.patch.object(hook, "ledger_today", lambda: []), \
                mock.patch.object(exits, "has_entry_plan", lambda s, path=None: has_plan), \
                redirect_stdout(buf), self.assertRaises(SystemExit) as code:
            cmd_check(args)
        return json.loads(buf.getvalue()), code.exception.code

    def test_allowed_with_plan(self):
        res, code = self.run_check(True)
        self.assertEqual((res["ok"], code), (True, 0))

    def test_refused_without_plan_like_the_hook(self):
        res, code = self.run_check(False)
        self.assertEqual((res["ok"], code), (False, 1))
        self.assertIn("no exit plan", res["reason"])


if __name__ == "__main__":
    unittest.main()
