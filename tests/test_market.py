import unittest
from datetime import date, datetime
from unittest import mock

import pandas as pd

from rhgex import market


def ticker(cal_date, reported_eps):
    """A stand-in yfinance Ticker: the calendar's next date, and get_earnings_dates with one row for that date."""
    t = mock.Mock()
    t.calendar = {"Earnings Date": [cal_date]}
    idx = pd.DatetimeIndex([datetime(cal_date.year, cal_date.month, cal_date.day, 2)])
    t.get_earnings_dates.return_value = pd.DataFrame({"Reported EPS": [reported_eps]}, index=idx)
    return t


class NextEarnings(unittest.TestCase):
    today = date(2026, 10, 15)

    def run_with(self, t):
        with mock.patch.object(market.yf, "Ticker", return_value=t):
            return market.next_earnings("TSM", today=self.today)

    def test_report_out_this_morning_is_past(self):
        self.assertIsNone(self.run_with(ticker(self.today, 4.60)))

    def test_report_due_later_today_is_kept(self):
        self.assertEqual(self.run_with(ticker(self.today, float("nan"))), self.today)

    def test_future_report_is_kept(self):
        self.assertEqual(self.run_with(ticker(date(2026, 10, 20), float("nan"))), date(2026, 10, 20))

    def test_failed_lookup_keeps_the_date(self):
        t = ticker(self.today, 4.60)
        t.get_earnings_dates.side_effect = RuntimeError("Yahoo down")
        self.assertEqual(self.run_with(t), self.today)


if __name__ == "__main__":
    unittest.main()
