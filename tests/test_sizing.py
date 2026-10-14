import unittest

from rhgex import sizing


class Sizing(unittest.TestCase):
    def test_option_contracts_fit_the_budget(self):
        s = sizing.option_contracts(1000, 25.0)  # 5% = $50 budget, $0.25 premium
        self.assertEqual((s["contracts"], s["risk"], s["fits"]), (2, 50.0, True))

    def test_option_too_expensive_does_not_fit(self):
        s = sizing.option_contracts(1000, 250.0)
        self.assertEqual((s["contracts"], s["fits"]), (0, False))

    def test_shares_sized_to_the_stop(self):
        s = sizing.shares(1000, 50, 45)  # 5% = $50 budget, $5 per share
        self.assertEqual((s["shares"], s["risk"], s["cost"]), (10, 50.0, 500.0))

    def test_bearish_stop_above_entry(self):
        self.assertEqual(sizing.shares(1000, 50, 52)["shares"], 25)

    def test_custom_pct(self):
        self.assertEqual(sizing.option_contracts(1000, 50, pct=10)["contracts"], 2)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            sizing.shares(1000, 10, 10)
        with self.assertRaises(ValueError):
            sizing.option_contracts(1000, 0)


if __name__ == "__main__":
    unittest.main()
