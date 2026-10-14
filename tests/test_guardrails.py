import unittest
from datetime import date

from rhgex import guardrails, hook

TODAY = date(2026, 10, 7)
CFG = {
    "limits": {"max_order_usd": 500, "max_option_premium_usd": 300, "min_option_dte": 7,
               "max_new_positions_per_day": 3, "max_daily_deployed_usd": 1500, "require_limit_orders": True},
    "blocked": [
        {"name": "S&P 500", "symbols": ["SPY", "VOO"], "until": ""},
        {"name": "ABC loss", "symbols": ["ABC"], "until": "2026-10-20"},
        {"name": "old", "symbols": ["OLD"], "until": "2026-09-01"},
    ],
}

# Fake instrument store: option_id -> (chain_symbol, type, strike, expiration)
INSTRUMENTS = {
    "nvda-c110": ("NVDA", "call", 110, "2026-11-20"),
    "nvda-c115": ("NVDA", "call", 115, "2026-11-20"),
    "nvda-c110-dec": ("NVDA", "call", 110, "2026-12-18"),
    "nvda-c110-soon": ("NVDA", "call", 110, "2026-10-10"),
    "voo-c600": ("VOO", "call", 600, "2026-11-20"),
    "abc1-c40": ("ABC1", "call", 40, "2026-11-20"),
    "spxw-c7900": ("SPXW", "call", 7900, "2026-11-20"),
}


def lookup(option_id):
    sym, typ, strike, exp = INSTRUMENTS[option_id]
    return {"chain_symbol": sym, "type": typ, "strike_price": str(strike), "expiration_date": exp}


def stock(ledger=(), today=TODAY, **args):
    order = hook.normalize("mcp__robinhood-trading__place_equity_order", {"account_number": "X", **args})
    return guardrails.check(CFG, order, list(ledger), today)


def option(legs, ledger=(), **args):
    legs = [{"option_id": i, "side": s, "position_effect": e} for i, s, e in legs]
    order = hook.normalize("mcp__robinhood-trading__place_option_order",
                           {"account_number": "X", "legs": legs, **args}, lookup)
    return guardrails.check(CFG, order, list(ledger), TODAY)


class Stock(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(stock(symbol="NVDA", side="buy", type="limit", quantity="2", limit_price="200")[0])

    def test_too_big(self):
        self.assertFalse(stock(symbol="NVDA", side="buy", type="limit", quantity="3", limit_price="200")[0])

    def test_market_order_refused(self):
        self.assertFalse(stock(symbol="NVDA", side="buy", type="market", quantity="1")[0])

    def test_buy_stop_market_refused(self):
        self.assertFalse(stock(symbol="NVDA", side="buy", type="stop_market", quantity="1", stop_price="250")[0])

    def test_market_price_ignored_without_limit_type(self):
        # a limit_price sent with type=market isn't a real limit
        self.assertFalse(stock(symbol="NVDA", side="buy", type="market", quantity="1", limit_price="1")[0])

    def test_dollar_order(self):
        self.assertTrue(stock(symbol="NVDA", side="buy", type="market", dollar_amount="400")[0])
        self.assertFalse(stock(symbol="NVDA", side="buy", type="market", dollar_amount="600")[0])

    def test_sell_and_stop_exits_allowed(self):
        self.assertTrue(stock(symbol="NVDA", side="sell", type="stop_market", quantity="5", stop_price="200")[0])


class WashSale(unittest.TestCase):
    def test_permanent_block(self):
        ok, reason = stock(symbol="SPY", side="buy", type="limit", quantity="1", limit_price="100")
        self.assertFalse(ok)
        self.assertIn("blocked", reason)

    def test_blocked_holdings_cant_be_sold(self):
        self.assertFalse(stock(symbol="ABC", side="sell", type="limit", quantity="10", limit_price="40")[0])
        self.assertFalse(option([("abc1-c40", "sell", "close")], quantity="1", price="1")[0])

    def test_block_covers_options(self):
        self.assertFalse(option([("voo-c600", "buy", "open")], quantity="1", price="1")[0])

    def test_adjusted_chain_still_blocked(self):
        self.assertFalse(option([("abc1-c40", "buy", "open")], quantity="1", price="1")[0])

    def test_dated_block_active_through_until(self):
        args = dict(symbol="ABC", side="buy", type="limit", quantity="1", limit_price="10")
        self.assertFalse(stock(today=date(2026, 10, 20), **args)[0])
        self.assertTrue(stock(today=date(2026, 10, 21), **args)[0])

    def test_expired_block(self):
        self.assertTrue(stock(symbol="OLD", side="buy", type="limit", quantity="1", limit_price="10")[0])

    def test_spx_allowed(self):
        self.assertTrue(option([("spxw-c7900", "buy", "open")], quantity="1", price="2.5")[0])


class Options(unittest.TestCase):
    def test_long_call(self):
        self.assertTrue(option([("nvda-c110", "buy", "open")], quantity="1", price="2.5")[0])

    def test_premium_cap(self):
        self.assertFalse(option([("nvda-c110", "buy", "open")], quantity="2", price="2.0")[0])

    def test_market_refused(self):
        self.assertFalse(option([("nvda-c110", "buy", "open")], quantity="1", type="market")[0])

    def test_short_single_refused(self):
        self.assertFalse(option([("nvda-c110", "sell", "open")], quantity="1", price="1")[0])

    def test_close_allowed(self):
        self.assertTrue(option([("nvda-c110", "sell", "close")], quantity="5", price="9")[0])

    def test_dte(self):
        self.assertFalse(option([("nvda-c110-soon", "buy", "open")], quantity="1", price="1")[0])

    def test_credit_spread_max_loss(self):
        legs = [("nvda-c110", "sell", "open"), ("nvda-c115", "buy", "open")]
        # width 5 - credit 1 = 4 -> $400 per spread > $300
        self.assertFalse(option(legs, quantity="1", price="1", direction="credit")[0])
        self.assertTrue(option(legs, quantity="1", price="2.5", direction="credit")[0])

    def test_debit_spread(self):
        legs = [("nvda-c110", "buy", "open"), ("nvda-c115", "sell", "open")]
        self.assertTrue(option(legs, quantity="1", price="2", direction="debit")[0])

    def test_spread_needs_direction(self):
        legs = [("nvda-c110", "sell", "open"), ("nvda-c115", "buy", "open")]
        self.assertFalse(option(legs, quantity="1", price="1")[0])

    def test_calendar_refused(self):
        legs = [("nvda-c110", "sell", "open"), ("nvda-c110-dec", "buy", "open")]
        self.assertFalse(option(legs, quantity="1", price="1", direction="debit")[0])


class Daily(unittest.TestCase):
    def test_max_positions(self):
        ledger = [{"opening": True, "cost_usd": 10}] * 3
        self.assertFalse(stock(ledger, symbol="NVDA", side="buy", type="limit", quantity="1", limit_price="10")[0])

    def test_deployed_cap(self):
        ledger = [{"opening": True, "cost_usd": 700}] * 2
        self.assertFalse(stock(ledger, symbol="NVDA", side="buy", type="limit", quantity="1", limit_price="200")[0])


PCT = {**CFG, "limits": {"max_order_pct": 100, "max_option_premium_pct": 25, "max_daily_deployed_pct": 100,
                         "min_option_dte": 7, "max_new_positions_per_day": 3, "require_limit_orders": True}}


def pct_stock(value, ledger=(), **args):
    order = hook.normalize("mcp__robinhood-trading__place_equity_order", {"account_number": "X", **args})
    return guardrails.check(PCT, order, list(ledger), TODAY, account_value=value)


class Percent(unittest.TestCase):
    def test_limit(self):
        self.assertEqual(guardrails.limit(PCT["limits"], "option_premium", 115.22), 28.8)
        self.assertEqual(guardrails.limit({"max_order_pct": 50, "max_order_usd": 40}, "order", 200), 40)
        self.assertEqual(guardrails.limit(CFG["limits"], "order", None), 500)  # dollars only
        with self.assertRaises(ValueError):
            guardrails.limit(PCT["limits"], "order", None)

    def test_scales_with_account(self):
        args = dict(symbol="NVDA", side="buy", type="limit", quantity="1", limit_price="110")
        self.assertTrue(pct_stock(115.22, **args)[0])
        ok, why = pct_stock(100, **args)
        self.assertFalse(ok)
        self.assertIn("$100.00", why)

    def test_unknown_value_refuses_entries_only(self):
        ok, why = pct_stock(None, symbol="NVDA", side="buy", type="limit", quantity="1", limit_price="50")
        self.assertFalse(ok)
        self.assertIn("get_portfolio", why)
        self.assertTrue(pct_stock(None, symbol="NVDA", side="sell", type="market", quantity="1")[0])

    def test_daily_deployed_pct(self):
        ledger = [{"opening": True, "cost_usd": 80}]
        ok, why = pct_stock(115.22, ledger, symbol="NVDA", side="buy", type="limit", quantity="1", limit_price="50")
        self.assertFalse(ok)
        self.assertIn("would deploy", why)


class AccountValue(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        self.path = Path(tempfile.mkdtemp()) / "account.json"
        mock.patch.object(hook, "ACCOUNT", self.path).start()
        self.addCleanup(mock.patch.stopall)

    def post(self, resp, acct="537"):
        hook.post({"tool_name": "mcp__robinhood-trading__get_portfolio", "tool_input": {"account_number": acct},
                   "tool_response": resp})

    def test_records_each_response_shape(self):
        import json
        body = json.dumps({"data": {"total_value": "115.22", "cash": "115.22"}, "guide": "..."})
        for resp in (body, [{"type": "text", "text": body}], {"content": [{"type": "text", "text": body}]},
                     json.loads(body)):
            self.path.unlink(missing_ok=True)
            self.post(resp)
            self.assertEqual(hook.account_value("537"), 115.22)
        self.assertIsNone(hook.account_value("other"))

    def test_garbage_records_nothing(self):
        self.post("not json")
        self.post({"data": {"total_value": "0"}})
        self.assertIsNone(hook.account_value("537"))

    def test_stale_value_ignored(self):
        import json
        self.path.write_text(json.dumps({"537": {"date": "2000-01-01", "total_value": 115.22}}))
        self.assertIsNone(hook.account_value("537"))


class Ledger(unittest.TestCase):
    """The ledger is synced through git: rows keep what the daily caps need and nothing about the account."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        self.path = Path(tempfile.mkdtemp()) / "ledger.jsonl"
        mock.patch.object(hook, "LEDGER", self.path).start()
        self.addCleanup(mock.patch.stopall)

    def test_row_has_no_account_details(self):
        import json
        resp = json.dumps({"data": {"id": "ord-1", "account": "https://api.robinhood.com/accounts/123456789/"}})
        hook.post({"tool_name": "mcp__robinhood-trading__place_equity_order",
                   "tool_input": {"account_number": "123456789", "symbol": "ktos", "side": "buy", "type": "limit",
                                  "quantity": "2", "limit_price": "10"},
                   "tool_response": resp})
        text = self.path.read_text()
        self.assertNotIn("123456789", text)
        row = json.loads(text)
        self.assertEqual({k: row[k] for k in ("tool", "order_id", "symbol", "side", "opening", "cost_usd")},
                         {"tool": "place_equity_order", "order_id": "ord-1", "symbol": "KTOS", "side": "buy",
                          "opening": True, "cost_usd": 20.0})
        self.assertEqual(len(hook.ledger_today()), 1)

    def test_unparseable_order_still_counts(self):
        import json
        hook.post({"tool_name": "mcp__robinhood-trading__place_equity_order",
                   "tool_input": {"account_number": "123456789"}, "tool_response": "not json"})
        row = json.loads(self.path.read_text())
        self.assertTrue(row["opening"])
        self.assertIsNone(row["order_id"])
        self.assertNotIn("123456789", json.dumps(row))


class Hook(unittest.TestCase):
    def test_classify(self):
        c = lambda n: hook.classify(f"mcp__robinhood-trading__{n}")
        self.assertEqual(c("get_option_positions"), "read")
        self.assertEqual(c("review_option_order"), "read")
        self.assertEqual(c("place_equity_order"), "order")
        self.assertEqual(c("cancel_equity_order"), "cancel")
        self.assertEqual(c("add_to_watchlist"), "harmless")
        self.assertEqual(c("exercise_option"), "ask")
        self.assertEqual(c("place_crypto_order"), "deny")
        self.assertEqual(c("replace_option_order"), "unknown")

    def test_unparseable(self):
        with self.assertRaises(ValueError):
            hook.normalize("place_equity_order", {"foo": 1})
        with self.assertRaises(ValueError):
            hook.normalize("place_option_order", {"legs": [{"option_id": "not-a-uuid", "side": "buy",
                                                            "position_effect": "open"}], "quantity": "1"})


if __name__ == "__main__":
    unittest.main()
