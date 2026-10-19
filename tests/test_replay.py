import unittest
from datetime import datetime, timedelta

from rhgex import replay
from rhgex.monitor import ET

MON = datetime(2026, 10, 19, 9, 30, tzinfo=ET)
CALL = {"symbol": "CRWV", "direction": "bullish", "setup": "downtrend-dip", "level": 60, "target": 65,
        "invalid": 58, "invalid_from": "his", "posted": "2026-10-19", "by": "2026-10-23"}


def session(day: datetime, rows: list[tuple]) -> list[dict]:
    """rows of (open, high, low, close, volume) from 09:30; the rest of the session flat at the last close."""
    bars = []
    for i in range(26):  # 09:30 ... 15:45
        o, h, lo, c, v = rows[i] if i < len(rows) else (rows[-1][3],) * 4 + (100,)
        bars.append({"start": day + timedelta(minutes=15 * i), "open": o, "high": h, "low": lo, "close": c,
                     "volume": v})
    return bars


HISTORY = session(MON - timedelta(days=3), [(61, 61.5, 60.8, 61, 100)])  # Friday: 26 quiet bars
SPY = session(MON - timedelta(days=3), [(700, 700, 700, 700, 1)]) + session(MON, [(700, 702, 699, 701, 1)])


def run(rows, call=CALL, account=1400):
    return replay.simulate(call, HISTORY + session(MON, rows), SPY, account)


class Simulate(unittest.TestCase):
    def test_reclaim_to_target(self):
        out = run([(60.5, 60.6, 59.6, 59.8, 300), (59.8, 60.5, 59.7, 60.4, 300), (60.4, 65.2, 60.3, 65, 300)])
        r = out["reclaim"]
        self.assertEqual((r["entry"], r["exit"], r["why"]), (60.4, 65, "target"))
        self.assertEqual(r["shares"], 17)  # $70 risk / 2.40 would be 29, but a $1,050 order (75%) caps it
        self.assertEqual(r["market_pct"], 0.14)  # SPY 700 -> 701 at the 09:45 bar
        d = out["dip"]
        self.assertEqual((d["entry"], d["why"]), (60, "target"))

    def test_same_day_exit_at_1545_and_held(self):
        out = run([(60.5, 60.6, 59.6, 59.8, 300), (59.8, 60.5, 59.7, 60.4, 300), (60.4, 61, 60.3, 61, 100)])
        self.assertEqual((out["reclaim"]["exit"], out["reclaim"]["why"]), (61, "15:45"))
        self.assertEqual(out["reclaim-held"]["why"], "open at end of data")

    def test_broke_the_stop_first(self):
        out = run([(60.5, 60.6, 57.9, 59, 300), (59, 60.6, 58.9, 60.4, 300)])
        self.assertEqual(out["reclaim"], "skip: traded through the stop first")
        self.assertEqual(out["dip"]["why"], "stop (same bar)")

    def test_needs_volume_and_reward_risk(self):
        out = run([(60.5, 60.6, 59.6, 59.8, 300), (59.8, 60.5, 59.7, 60.4, 50), (60.4, 60.5, 59.5, 59.9, 50)])
        self.assertEqual(out["reclaim"], "skip: no confirmed reclaim")  # volume below its average
        out = run([(60.5, 60.6, 59.6, 59.8, 300), (59.8, 62.5, 59.7, 62.2, 300)])
        self.assertTrue(out["reclaim"].startswith("skip: R:R 0.67"))  # 2.8 to go vs 4.2 at risk

    def test_never_touched(self):
        self.assertEqual(run([(61, 62, 60.5, 61.5, 300)])["dip"], "skip: never touched his level")

    def test_posted_mid_session_counts_from_the_post(self):
        call = CALL | {"posted_at": "2026-10-19T07:20"}  # 10:20 ET from a Pacific machine
        out = replay.simulate(call, HISTORY + session(MON, [(60.5, 60.6, 59.6, 59.8, 300), (59.8, 60.5, 59.7,
                              60.4, 300), (60.4, 61, 60.3, 61, 100)]), SPY, 1400)
        self.assertEqual(out["dip"], "skip: never touched his level")  # the touch was before he posted


class Run(unittest.TestCase):
    def test_filters_and_splits(self):
        calls = [CALL, CALL | {"symbol": "ASTS", "invalid_from": "atr"},
                 CALL | {"symbol": "NVDA", "setup": "breakout"}, CALL | {"symbol": "SMCI", "direction": "bearish"}]
        rows = [(60.5, 60.6, 59.6, 59.8, 300), (59.8, 60.5, 59.7, 60.4, 300), (60.4, 65.2, 60.3, 65, 300)]
        fetch = lambda s: SPY if s == "SPY" else HISTORY + session(MON, rows)  # noqa: E731
        out = replay.run(1400, calls=calls, fetch=fetch)
        self.assertEqual([r["symbol"] for r in out["calls"]], ["CRWV", "ASTS"])
        s = out["summary"]["reclaim"]
        self.assertEqual((s["all"]["trades"], s["stop: his"]["trades"], s["stop: atr"]["trades"]), (2, 1, 1))
        self.assertEqual((s["market up at entry"]["trades"], s["market down at entry"]["trades"]), (2, 0))
        self.assertEqual(s["all"]["net"], round(2 * 17 * 4.6, 2))


if __name__ == "__main__":
    unittest.main()
