import unittest

from rhgex.indicators import atr, ema, rsi


class Indicators(unittest.TestCase):
    def test_ema(self):
        self.assertEqual(ema([10.0] * 5, 3), [10.0] * 5)
        out = ema([10.0, 20.0, 20.0], 3)  # k = 0.5
        self.assertEqual(out, [10.0, 15.0, 17.5])

    def test_rsi(self):
        self.assertEqual(rsi(list(range(1, 17))), 100.0)                     # only gains
        self.assertAlmostEqual(rsi(list(range(16, 0, -1))), 0.0)             # only losses
        self.assertAlmostEqual(rsi([10, 11] * 8 + [10]), 50.0)               # equal gains and losses

    def test_atr_uses_the_true_range(self):
        highs, lows, closes = [11.0] * 15, [9.0] * 15, [10.0] * 15
        self.assertEqual(atr(highs, lows, closes), 2.0)
        closes[-2] = 14.0  # a gap: the last bar's true range is |low - prior close| = 5
        self.assertAlmostEqual(atr(highs, lows, closes), (2.0 * 13 + 5.0) / 14)


if __name__ == "__main__":
    unittest.main()
