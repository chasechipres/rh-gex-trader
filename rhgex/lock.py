"""One machine at a time: a session lock in private/state/session.lock, synced through the private repo.

A cycle acquires the lock (then commits and pushes it) before placing orders, and releases it at the end. A
lock held by another machine blocks orders until it's older than STALE_HOURS, so a machine that crashed or slept
mid-cycle can't block the other one forever.
"""

import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

from . import paths

LOCK = paths.STATE / "session.lock"
STALE_HOURS = 3  # full cycles run up to ~2.5 h apart; each one refreshes the lock


def machine() -> str:
    return socket.gethostname()


def read(path: Path = LOCK) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def acquire(path: Path = LOCK, me: str | None = None, now: datetime | None = None) -> dict:
    me, now = me or machine(), now or datetime.now()
    held = read(path)
    if held and held["machine"] != me:
        age = now - datetime.fromisoformat(held["time"])
        if age < timedelta(hours=STALE_HOURS):
            raise ValueError(f"{held['machine']} holds the session lock since {held['time']} "
                             f"({int(age.total_seconds() // 60)} min ago); place no orders from this machine")
    lock = {"machine": me, "time": now.isoformat(timespec="seconds")}
    paths.ensure(path.parent)
    path.write_text(json.dumps(lock))
    return lock


def release(path: Path = LOCK, me: str | None = None) -> dict:
    me = me or machine()
    held = read(path)
    if held and held["machine"] == me:
        path.unlink()
        return {"released": True}
    return {"released": False, "held_by": held["machine"] if held else None}
