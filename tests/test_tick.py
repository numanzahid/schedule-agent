from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from schedule_agent.tick import job_is_due


TZ = timezone(timedelta(hours=5))


def job(**kwargs):
    base = {
        "id": "demo",
        "enabled": True,
        "lastRun": None,
        "lastStatus": None,
        "schedule": {"type": "cron", "expr": "0 6 * * *"},
    }
    base.update(kwargs)
    return base


class TickTests(unittest.TestCase):
    def test_cron_matches_current_minute(self) -> None:
        now = datetime(2026, 9, 16, 6, 0, tzinfo=TZ)
        self.assertTrue(job_is_due(job(), now))

    def test_cron_skips_other_minute(self) -> None:
        now = datetime(2026, 9, 16, 6, 1, tzinfo=TZ)
        self.assertFalse(job_is_due(job(), now))

    def test_cron_skips_same_minute_rerun(self) -> None:
        now = datetime(2026, 9, 16, 6, 0, tzinfo=TZ)
        self.assertFalse(
            job_is_due(job(lastRun=now.isoformat()), now)
        )

    def test_cron_catchup_after_sleep(self) -> None:
        last = datetime(2026, 9, 15, 6, 0, tzinfo=TZ)
        now = datetime(2026, 9, 16, 8, 30, tzinfo=TZ)
        self.assertTrue(job_is_due(job(lastRun=last.isoformat()), now))

    def test_disabled_not_due(self) -> None:
        now = datetime(2026, 9, 16, 6, 0, tzinfo=TZ)
        self.assertFalse(job_is_due(job(enabled=False), now))

    def test_at_future(self) -> None:
        now = datetime(2026, 9, 16, 10, 0, tzinfo=TZ)
        future = now + timedelta(hours=2)
        item = job(
            schedule={"type": "at", "runAt": future.isoformat()},
        )
        self.assertFalse(job_is_due(item, now))
        self.assertTrue(job_is_due(item, future))

    def test_at_skips_after_ok(self) -> None:
        now = datetime(2026, 9, 16, 10, 0, tzinfo=TZ)
        item = job(
            lastStatus="ok",
            schedule={"type": "at", "runAt": now.isoformat()},
        )
        self.assertFalse(job_is_due(item, now))


if __name__ == "__main__":
    unittest.main()
