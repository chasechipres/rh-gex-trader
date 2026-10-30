import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from rhgex import exits, monitor, watches

ET = monitor.ET
MON = datetime(2026, 10, 19, 10, 30, tzinfo=ET)  # a Monday, mid-session


def bar(start: datetime, low: float, close: float, volume: float = 100) -> dict:
    return {"start": start, "low": low, "close": close, "volume": volume}


class Clock:
    """now() advances by the interval each time sleep() is called."""

    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)


class Base(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.watches, self.plans, self.fired = d / "watches.json", d / "plans.json", d / "monitor.json"
        self.lines = []

    def run_monitor(self, prices, minutes=3, start=MON, bars=lambda s: [], close="16:00"):
        clock = Clock(start)
        quotes = prices if callable(prices) else (lambda syms, t: {s: prices[s] for s in syms if s in prices})
        state = monitor.run(minutes, 60, close, emit=self.lines.append, now=clock.now, sleep=clock.sleep,
                            quotes=quotes, bars=bars, fired_path=self.fired, watches_path=self.watches,
                            plans_path=self.plans)
        return state, [json.loads(line) for line in self.lines]

    def watch(self, *a, **k):
        return watches.add(*a, today=MON.date(), path=self.watches, **k)

    def plan(self, *a, **k):
        return exits.add(*a, path=self.plans, **k)


class Events(Base):
    def test_watch_triggers_each_side(self):
        self.watch("MU", "above", 922, "breakout", stop=905, target=950)
        self.watch("CRWV", "below", 63, "breakdown", stop=65, target=60)
        state, out = self.run_monitor({"MU": 923.1, "CRWV": 64})
        self.assertEqual(state, "EVENT")
        self.assertEqual([(e["event"], e["symbol"]) for e in out[:-1]], [("WATCH_TRIGGERED", "MU")])

    def test_plan_levels_bullish_and_bearish(self):
        self.plan("NVDA", "stock", "bullish", 212, 225, "x", price=216)
        self.plan("NVD", "stock", "bearish", 222, 205, "y", price=216)  # an inverse fund, on NVDA's levels
        _, out = self.run_monitor({"NVDA": 211.9})
        got = {(e["event"], e["symbol"]) for e in out[:-1]}
        self.assertEqual(got, {("STOP_HIT", "NVDA")})  # bearish: 1R in profit only at 210
        self.lines.clear()
        self.fired.unlink()
        _, out = self.run_monitor({"NVDA": 209.5})
        self.assertIn(("AT_1R", "NVD", "NVDA"), {(e["event"], e["symbol"], e["underlying"]) for e in out[:-1]})

    def test_fund_plan_quotes_its_stock(self):
        self.plan("NVDL", "stock", "bullish", 212, 225, "[leveraged trial]", price=216)
        _, out = self.run_monitor({"NVDA": 225.5, "NVDL": 99})
        self.assertEqual(out[0]["event"], "TARGET_HIT")
        self.assertEqual((out[0]["symbol"], out[0]["level"]), ("NVDL", 225))

    def test_fires_once_per_level_and_day(self):
        p = self.plan("MU", "stock", "bullish", 880, 950, "x", price=900)
        self.assertEqual(self.run_monitor({"MU": 951})[0], "EVENT")
        self.lines.clear()
        state, out = self.run_monitor({"MU": 952}, minutes=2)
        self.assertEqual((state, len(out)), ("HEARTBEAT", 1))  # handled already: no second wake-up
        self.lines.clear()
        exits.raise_stop("MU", 945, path=self.plans)  # a new level can fire
        _, out = self.run_monitor({"MU": 944})
        self.assertEqual((out[0]["event"], out[0]["level"]), ("STOP_HIT", 945))
        self.assertTrue(p)

    def test_same_day_exit_for_reclaim_positions(self):
        self.plan("CRWV", "stock", "bullish", 58, 65, "[reclaim] his 60 king", price=60.5)
        state, _ = self.run_monitor({"CRWV": 61}, minutes=5, start=MON.replace(hour=15, minute=40))
        self.assertEqual(state, "EVENT")
        self.assertEqual(json.loads(self.lines[0])["event"], "SAME_DAY_EXIT")
        self.assertEqual(json.loads(self.lines[0])["time"], "15:45")


class Terminal(Base):
    def test_idle_closed_heartbeat(self):
        self.assertEqual(self.run_monitor({})[0], "IDLE")
        self.watch("MU", "above", 922, "", stop=905, target=950)
        self.assertEqual(self.run_monitor({"MU": 900}, start=MON.replace(hour=9, minute=10))[0], "CLOSED")
        self.assertEqual(self.run_monitor({"MU": 900}, start=MON.replace(hour=12, minute=59), close="13:00")[0],
                         "CLOSED")  # early close: one poll at 12:59, then closed
        state, out = self.run_monitor({"MU": 900}, minutes=3)
        self.assertEqual((state, out[-1]["watching"]), ("HEARTBEAT", ["MU"]))

    def test_feed_down(self):
        self.watch("MU", "above", 922, "", stop=905, target=950)
        state, out = self.run_monitor({}, minutes=30)
        self.assertEqual((state, out[-1]["symbols"]), ("FEED_DOWN", ["MU"]))
        self.assertEqual(out[-1]["time"], "10:34")  # five missed polls, a minute apart

    def test_expired_watch_is_not_watched(self):
        watches.add("MU", "above", 922, "", until="2026-10-16", today=MON.date().replace(day=15), path=self.watches)
        self.assertEqual(self.run_monitor({"MU": 930})[0], "IDLE")


class Log(Base):
    def test_runs_are_logged_and_summed(self):
        log = self.fired.parent / "monitor.jsonl"
        self.watch("MU", "above", 922, "", stop=905, target=950)
        clock = Clock(MON)
        for px in (900, 923):
            monitor.run(30, 60, emit=self.lines.append, now=clock.now, sleep=clock.sleep,
                        quotes=lambda syms, t, px=px: {"MU": px}, fired_path=self.fired,
                        watches_path=self.watches, plans_path=self.plans, log_path=log)
        day = monitor.stats(log)[0]
        self.assertEqual((day["runs"], day["minutes"], day["loop_15min_checks"]), (2, 30, 2))
        self.assertEqual((day["ended"], day["events"]), ({"HEARTBEAT": 1, "EVENT": 1}, {"WATCH_TRIGGERED": 1}))
        self.assertEqual(monitor.stats(log, since="2026-10-20"), [])


class Reclaim(Base):
    """CRWV, his $60 king with a $58 invalidation, on 15-minute bars."""

    def setUp(self):
        super().setUp()
        self.w = self.watch("CRWV", "above", 60, "his 60 king", stop=58, target=65, reclaim=True)
        self.w["opened"] = "2026-10-19T06:00:00"  # Pacific, before the open
        watches.save([self.w], self.watches)
        self.open = MON.replace(hour=9, minute=30)
        self.history = [bar(self.open - timedelta(days=1, minutes=15 * i), 61, 61.5) for i in range(20)]

    def bars(self, *today):
        return lambda s: self.history + [bar(self.open + timedelta(minutes=15 * i), lo, c, v)
                                         for i, (lo, c, v) in enumerate(today)]

    def test_confirmed_after_a_touch(self):
        b = self.bars((59.6, 59.9, 300), (59.8, 60.4, 250))  # touched 60, then closed back above on volume
        self.assertEqual(monitor.reclaim(self.w, b("CRWV"), self.open + timedelta(minutes=30)), "CONFIRMED")
        self.assertIsNone(monitor.reclaim(self.w, b("CRWV"), self.open + timedelta(minutes=29)))  # bar not done
        state, out = self.run_monitor({"CRWV": 60.5}, start=self.open + timedelta(minutes=30), bars=b)
        self.assertEqual((state, out[0]["event"]), ("EVENT", "RECLAIM_CONFIRMED"))

    def test_needs_touch_volume_and_time(self):
        now = self.open + timedelta(minutes=30)
        self.assertIsNone(monitor.reclaim(self.w, self.bars((60.2, 60.5, 300), (60.3, 60.8, 300))("X"), now))
        self.assertIsNone(monitor.reclaim(self.w, self.bars((59.6, 59.9, 300), (59.8, 60.4, 90))("X"), now))
        late = [(59.6, 59.9, 300)] * 24 + [(59.8, 60.4, 400)]  # the 15:30-15:45 bar is too late
        self.assertIsNone(monitor.reclaim(self.w, self.bars(*late)("X"), self.open + timedelta(minutes=375)))

    def test_invalidated_through_his_stop(self):
        b = self.bars((57.9, 59.0, 300), (58.5, 60.4, 300))  # broke 58 before reclaiming
        self.assertEqual(monitor.reclaim(self.w, b("X"), self.open + timedelta(minutes=30)), "INVALIDATED")
        _, out = self.run_monitor({"CRWV": 57.5}, start=self.open + timedelta(minutes=5), bars=self.bars())
        self.assertEqual(out[0]["event"], "RECLAIM_INVALIDATED")

    def test_price_cross_alone_does_not_fire(self):
        state, _ = self.run_monitor({"CRWV": 61}, start=self.open + timedelta(minutes=5), bars=self.bars())
        self.assertEqual(state, "HEARTBEAT")

    def test_watch_add_and_check(self):
        with self.assertRaises(ValueError):
            self.watch("CRWV", "below", 60, "", stop=62, target=55, reclaim=True)
        with self.assertRaises(ValueError):
            self.watch("CRWV", "above", 60, "", reclaim=True)
        r = watches.check({"CRWV": 60.5}, MON.date(), self.watches)[0]  # above the level, never dipped: no signal
        self.assertEqual((r["state"], r["confirm"], r["stop"]), ("WAITING", "reclaim", 58))

    def test_watch_check_states(self):
        def state(px, bars, minutes=30):
            return watches.check({"CRWV": px}, MON.date(), self.watches, bars=bars,
                                 now=self.open + timedelta(minutes=minutes))[0]["state"]
        self.assertEqual(state(61, self.bars((60.3, 60.8, 300), (60.5, 61, 300))), "WAITING")  # stayed above 60
        self.assertEqual(state(59.8, self.bars()), "RECLAIM_PENDING")  # the price itself is at the level
        self.assertEqual(state(60.2, self.bars((59.6, 59.9, 300), (59.8, 60.1, 90))), "RECLAIM_PENDING")  # thin
        self.assertEqual(state(60.5, self.bars((59.6, 59.9, 300), (59.8, 60.4, 250))), "RECLAIM_CONFIRMED")
        self.assertEqual(state(57.9, self.bars()), "RECLAIM_INVALIDATED")

    def test_outlier_volume_does_not_confirm(self):
        # one bar at ~25x the average (Yahoo's bad print): not a confirmation, the next normal bar is
        now = self.open + timedelta(minutes=30)
        b = self.bars((59.6, 59.9, 300), (59.8, 60.4, 2500))
        state, info = monitor.reclaim_status(self.w, b("X"), now)
        self.assertEqual((state, info["suspect_volume"]), ("PENDING", True))
        state, _ = self.run_monitor({"CRWV": 60.5}, start=now, bars=b)
        self.assertEqual(state, "HEARTBEAT")
        b = self.bars((59.6, 59.9, 300), (59.8, 60.4, 2500), (60.1, 60.5, 300))
        state, info = monitor.reclaim_status(self.w, b("X"), now + timedelta(minutes=15))
        self.assertEqual((state, info["bar_volume"]), ("CONFIRMED", 300))


if __name__ == "__main__":
    unittest.main()
