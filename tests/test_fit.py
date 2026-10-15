import unittest
from datetime import date

from rhgex import fit


def leg(kind, strike, bid, ask, oi=2000, delta=0.5, expiry="2026-10-30"):
    return {"expiry": expiry, "dte": 16, "kind": kind, "strike": strike, "bid": bid, "ask": ask,
            "mid": (bid + ask) / 2, "oi": oi, "delta": delta}


class Fit(unittest.TestCase):
    def test_vertical_fits_where_the_single_does_not(self):
        rows = [leg("call", 100, 4.00, 4.20), leg("call", 102, 3.10, 3.25, oi=150, delta=0.4),
                leg("call", 110, 0.80, 0.85, delta=0.15)]
        got = fit.candidates(rows, "bullish", target=103, budget=112)
        self.assertEqual([(c["structure"], c["buy"], c["sell"]) for c in got], [("call vertical", 100, 102)])
        c = got[0]
        self.assertEqual((c["debit"], c["cost_per_contract"], c["contracts"], c["value_at_target"]), (0.92, 92.0, 1, 200))
        self.assertEqual(c["legs"], ["4.0,4.2,2000", "3.1,3.25,150"])

    def test_short_leg_stays_inside_the_target_and_must_pay(self):
        rows = [leg("call", 100, 1.00, 1.05), leg("call", 105, 0.40, 0.45, delta=0.3)]
        got = fit.candidates(rows, "bullish", target=104, budget=500)  # 105 is past the target
        self.assertEqual([(c["buy"], c["sell"]) for c in got], [(100, None)])
        self.assertEqual(fit.candidates(rows, "bullish", target=100.5, budget=500), [])  # 0.50 < 1.025 debit

    def test_bearish_uses_puts_below(self):
        rows = [leg("put", 50, 1.50, 1.55, delta=-0.5), leg("put", 48, 0.70, 0.75, delta=-0.3, oi=120),
                leg("put", 52, 2.90, 3.00, delta=-0.7), leg("call", 50, 1.50, 1.55)]
        got = fit.candidates(rows, "bearish", target=47, budget=100)
        self.assertEqual({(c["structure"], c["buy"], c["sell"]) for c in got}, {("put vertical", 50, 48)})

    def test_illiquid_legs_are_dropped(self):
        rows = [leg("call", 100, 0.50, 0.80), leg("call", 101, 0.30, 0.35, oi=50, delta=0.4)]
        self.assertEqual(fit.candidates(rows, "bullish", target=105, budget=500), [])

    def test_legs_parses_cboe_rows_in_window(self):
        data = {"options": [
            {"option": "XYZ261030C00100000", "bid": 1.0, "ask": 1.1, "open_interest": 900, "delta": 0.5},
            {"option": "XYZ261016C00100000", "bid": 1.0, "ask": 1.1, "open_interest": 900, "delta": 0.5},
            {"option": "XYZ261030P00100000", "bid": 0, "ask": 0, "open_interest": 900, "delta": -0.5}]}
        got = fit.legs(data, date(2026, 10, 14), 14, 45)
        self.assertEqual([(r["kind"], r["strike"], r["dte"]) for r in got], [("call", 100.0, 16)])


if __name__ == "__main__":
    unittest.main()
