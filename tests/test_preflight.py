import tempfile
import unittest
from datetime import date
from pathlib import Path

from rhgex import preflight
from rhgex.preflight import Candidate, Context

TODAY = date(2026, 10, 14)  # Wednesday
POST = "https://x.com/Han_Akamatsu/status/111"


def ctx(**kw):
    base = dict(today=TODAY, blocks={"SPY": "401k"}, plans=[], journal=[], posts={"111": date(2026, 10, 13)},
                opened_today=0, max_new_per_day=3, earnings=lambda s: None, sector=lambda s: "Technology")
    return Context(**{**base, **kw})


def good(**kw):
    base = dict(symbol="ORCL", direction="bullish", price=145, stop=137, target=158, asset="option",
                expiration="2026-10-30", legs=[(3.10, 3.30, 2500), (1.00, 1.08, 1800)], source=POST)
    return Candidate(**{**base, **kw})


def failed(checks):
    return {c["check"] for c in checks if not c["ok"]}


def plan(sym, stop=100, price=110):
    return {"symbol": sym, "direction": "bullish", "stop": stop, "price": price}


class Preflight(unittest.TestCase):
    def test_clean_trade_passes(self):
        self.assertEqual(failed(preflight.evaluate(good(), ctx())), set())

    def test_blocked_and_reward_risk(self):
        self.assertIn("blocked", failed(preflight.evaluate(good(symbol="SPY"), ctx())))
        self.assertIn("reward_risk", failed(preflight.evaluate(good(target=150), ctx())))

    def test_entry_cap_reports_the_breakout_limit(self):
        cap = {c["check"]: c for c in preflight.evaluate(good(), ctx())}["entry_cap"]
        self.assertTrue(cap["ok"])
        self.assertIn("highest ORCL entry for 1.5 R:R: 145.4", cap["detail"])  # (158 + 1.5 * 137) / 2.5

    def test_entry_cap_translates_to_the_fund(self):
        c = good(symbol="MUU", asset="stock", legs=[], price=922, stop=905, target=950, quote=(26.70, 26.74))
        cap = {c["check"]: c for c in preflight.evaluate(c, ctx())}["entry_cap"]
        self.assertIn("highest MU entry for 1.5 R:R: 923.0", cap["detail"])
        self.assertIn("MUU limit cap 26.78", cap["detail"])  # 26.72 * (1 + 2 * (923 / 922 - 1))

    def test_dte_and_earnings_before_expiry(self):
        self.assertIn("dte", failed(preflight.evaluate(good(expiration="2026-10-20"), ctx())))
        c = ctx(earnings=lambda s: date(2026, 10, 27))
        self.assertIn("earnings", failed(preflight.evaluate(good(), c)))
        self.assertNotIn("earnings", failed(preflight.evaluate(good(earnings_play=True), c)))

    def test_shorter_expiry_before_earnings(self):
        c = ctx(earnings=lambda s: date(2026, 10, 28))
        self.assertNotIn("dte", failed(preflight.evaluate(good(expiration="2026-10-23"), c)))  # 9 days, before
        self.assertIn("dte", failed(preflight.evaluate(good(expiration="2026-10-20"), c)))  # 6 days: too short
        self.assertIn("dte", failed(preflight.evaluate(good(expiration="2026-10-23"), ctx())))  # no earnings

    def test_liquidity(self):
        self.assertIn("liquidity_leg1", failed(preflight.evaluate(good(legs=[(1.00, 1.30, 2500)]), ctx())))  # 26%
        self.assertIn("liquidity_leg1", failed(preflight.evaluate(good(legs=[(3.10, 3.30, 200)]), ctx())))  # OI
        self.assertIn("liquidity", failed(preflight.evaluate(good(legs=[]), ctx())))

    def test_shares_skip_liquidity_but_check_earnings_soon(self):
        c = ctx(earnings=lambda s: date(2026, 10, 19))  # Monday: 3 trading days
        self.assertEqual(failed(preflight.evaluate(good(asset="stock", legs=[]), c)), {"earnings"})

    def test_open_risk_counts_only_positions_below_breakeven(self):
        risky = [plan(s) for s in "ABCDE"]
        self.assertIn("open_risk", failed(preflight.evaluate(good(), ctx(plans=risky, sector=None))))
        safe = risky[:4] + [plan("E", stop=110)]  # E's stop is at breakeven
        self.assertNotIn("open_risk", failed(preflight.evaluate(good(), ctx(plans=safe, sector=None))))

    def test_sector_cap(self):
        self.assertIn("sector", failed(preflight.evaluate(good(), ctx(plans=[plan("NVDA"), plan("MSFT")]))))

    def test_fresh_post(self):
        self.assertIn("fresh_post", failed(preflight.evaluate(good(), ctx(posts={"111": date(2026, 10, 9)}))))
        self.assertIn("fresh_post", failed(preflight.evaluate(good(source="own idea"), ctx())))

    def test_revenge_window(self):
        loss = [{"symbol": "ORCL", "action": "exit", "pnl": -40, "time": "2026-10-13T12:00:00"}]
        self.assertIn("revenge", failed(preflight.evaluate(good(), ctx(journal=loss))))
        self.assertNotIn("revenge", failed(preflight.evaluate(good(new_setup=True), ctx(journal=loss))))
        old = [{**loss[0], "time": "2026-10-08T12:00:00"}]
        self.assertNotIn("revenge", failed(preflight.evaluate(good(), ctx(journal=old))))

    def test_daily_count(self):
        self.assertIn("daily_count", failed(preflight.evaluate(good(), ctx(opened_today=3))))

    def test_saved_posts_uses_earliest_note(self):
        d = Path(tempfile.mkdtemp())
        (d / "2026-10-12-0600-a.md").write_text("Link: https://x.com/H/status/111", encoding="utf-8")
        (d / "2026-10-13-0900-b.md").write_text("Related: https://x.com/H/status/111 and /status/222",
                                                 encoding="utf-8")
        self.assertEqual(preflight.saved_posts(d), {"111": date(2026, 10, 12), "222": date(2026, 10, 13)})


if __name__ == "__main__":
    unittest.main()
