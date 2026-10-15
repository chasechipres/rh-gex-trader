import unittest
from datetime import date, timedelta
from unittest import mock

from rhgex import gex


def occ(kind: str, strike: float, days: int) -> str:
    exp = date.today() + timedelta(days=days)
    return f"XYZ{exp:%y%m%d}{kind}{int(strike * 1000):08d}"


def option(kind, strike, oi, days=20, iv=0.5):
    spot = 100.0
    years = max(days, 0.5) / 365
    return {"option": occ(kind, strike, days), "open_interest": oi, "iv": iv,
            "gamma": gex.bs_gamma(spot, strike, iv, years)}


def chain(*options):
    return {"current_price": 100.0, "last_trade_time": "2026-10-15T16:00:00", "iv30": 50.0, "options": list(options)}


class Gamma(unittest.TestCase):
    def test_bs_gamma_peaks_at_the_money(self):
        atm, otm = gex.bs_gamma(100, 100, 0.5, 0.1), gex.bs_gamma(100, 130, 0.5, 0.1)
        self.assertGreater(atm, otm)
        self.assertGreater(otm, 0)
        self.assertEqual(gex.bs_gamma(100, 100, 0, 0.1), 0.0)
        self.assertEqual(gex.bs_gamma(100, 100, 0.5, 0), 0.0)


class Profile(unittest.TestCase):
    def run_with(self, data, **kw):
        with mock.patch.object(gex, "chain", return_value=data):
            return gex.profile("XYZ", **kw)

    def test_walls_regime_and_flip(self):
        # calls stacked above spot outweigh puts below: positive gamma at spot, and the sign flips lower down
        p = self.run_with(chain(option("C", 105, 20_000), option("C", 110, 5_000),
                                option("P", 95, 8_000), option("P", 90, 15_000)))
        self.assertEqual((p["call_wall_within_10pct"], p["put_wall_within_10pct"]), (105, 90))
        self.assertTrue(p["regime"].startswith("positive"))
        self.assertIsNotNone(p["zero_gamma_flip"])
        self.assertLess(p["zero_gamma_flip"], 100)
        self.assertEqual(p["top_strikes_within_10pct"][0]["strike"], 105)

    def test_puts_dominate_is_negative_gamma(self):
        p = self.run_with(chain(option("C", 105, 1_000), option("P", 98, 30_000)))
        self.assertTrue(p["regime"].startswith("negative"))
        self.assertLess(p["total_gex_usd_per_1pct"], 0)

    def test_filters(self):
        p = self.run_with(chain(option("C", 105, 1_000), option("C", 106, 0),        # no open interest
                                option("C", 107, 1_000, days=90),                    # past max_days
                                option("C", 108, 1_000, iv=0.001)), max_days=45)      # no usable IV
        self.assertEqual(p["contracts_used"], 1)
        self.assertIn("error", self.run_with(chain(option("C", 106, 0))))


if __name__ == "__main__":
    unittest.main()
