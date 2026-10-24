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

    def test_never_run_cron_recovers_first_missed_occurrence(self) -> None:
        created = datetime(2026, 9, 15, 12, 0, tzinfo=TZ)
        now = datetime(2026, 9, 16, 8, 30, tzinfo=TZ)
        self.assertTrue(job_is_due(job(createdAt=created.isoformat()), now))

    def test_never_run_cron_does_not_replay_before_creation(self) -> None:
        created = datetime(2026, 9, 16, 6, 0, 10, tzinfo=TZ)
        now = datetime(2026, 9, 16, 8, 30, tzinfo=TZ)
        self.assertFalse(job_is_due(job(createdAt=created.isoformat()), now))

    def test_cron_does_not_run_before_creation(self) -> None:
        created = datetime(2026, 9, 17, 6, 0, tzinfo=TZ)
        now = datetime(2026, 9, 16, 6, 0, tzinfo=TZ)
        self.assertFalse(job_is_due(job(createdAt=created.isoformat()), now))

    def test_weekly_catchup_more_than_twenty_four_hours_late(self) -> None:
        last = datetime(2026, 9, 7, 9, 0, tzinfo=TZ)
        now = datetime(2026, 9, 16, 12, 0, tzinfo=TZ)
        item = job(lastRun=last.isoformat(), schedule={"type": "cron", "expr": "0 9 * * mon"})
        self.assertTrue(job_is_due(item, now))

    def test_annual_catchup_after_long_downtime(self) -> None:
        last = datetime(2020, 1, 1, tzinfo=TZ)
        now = datetime(2026, 9, 16, tzinfo=TZ)
        item = job(lastRun=last.isoformat(), schedule={"type": "cron", "expr": "0 0 1 1 *"})
        self.assertTrue(job_is_due(item, now))

    def test_cron_interval_excludes_previous_attempt(self) -> None:
        last = datetime(2026, 9, 14, 9, 0, tzinfo=TZ)
        now = datetime(2026, 9, 16, 12, 0, tzinfo=TZ)
        item = job(lastRun=last.isoformat(), schedule={"type": "cron", "expr": "0 9 * * mon"})
        self.assertFalse(job_is_due(item, now))

    def test_cron_compares_offsets_in_current_timezone(self) -> None:
        last = datetime(2026, 9, 16, 0, 59, tzinfo=timezone.utc)
        now = datetime(2026, 9, 16, 6, 1, tzinfo=TZ)
        self.assertTrue(job_is_due(job(lastRun=last.isoformat()), now))

    def test_retry_backoff_blocks_due_one_shot_until_retry_time(self) -> None:
        now = datetime(2026, 9, 16, 10, 0, tzinfo=TZ)
        retry = now + timedelta(minutes=2)
        item = job(lastStatus="failed", nextRetryAt=retry.isoformat(),
                   schedule={"type": "at", "runAt": now.isoformat()})
        self.assertFalse(job_is_due(item, now))
        self.assertTrue(job_is_due(item, retry))

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
