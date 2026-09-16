from __future__ import annotations

import unittest
from datetime import datetime

from schedule_agent.cron import cron_matches, parse_cron


class CronTests(unittest.TestCase):
    def test_daily_6am(self) -> None:
        expr = "0 6 * * *"
        self.assertTrue(cron_matches(expr, datetime(2026, 9, 16, 6, 0)))
        self.assertFalse(cron_matches(expr, datetime(2026, 9, 16, 6, 1)))
        self.assertFalse(cron_matches(expr, datetime(2026, 9, 16, 7, 0)))

    def test_every_15_minutes(self) -> None:
        expr = "*/15 * * * *"
        self.assertTrue(cron_matches(expr, datetime(2026, 9, 16, 10, 0)))
        self.assertTrue(cron_matches(expr, datetime(2026, 9, 16, 10, 45)))
        self.assertFalse(cron_matches(expr, datetime(2026, 9, 16, 10, 7)))

    def test_monday_9am(self) -> None:
        expr = "0 9 * * 1"
        monday = datetime(2026, 9, 14, 9, 0)
        tuesday = datetime(2026, 9, 15, 9, 0)
        self.assertEqual(monday.weekday(), 0)
        self.assertTrue(cron_matches(expr, monday))
        self.assertFalse(cron_matches(expr, tuesday))

    def test_sunday_zero_and_seven(self) -> None:
        sunday = datetime(2026, 9, 20, 8, 0)
        self.assertEqual(sunday.weekday(), 6)
        self.assertTrue(cron_matches("0 8 * * 0", sunday))
        self.assertTrue(cron_matches("0 8 * * 7", sunday))
        self.assertFalse(cron_matches("0 8 * * 1", sunday))

    def test_named_dow(self) -> None:
        monday = datetime(2026, 9, 14, 9, 0)
        self.assertTrue(cron_matches("0 9 * * mon", monday))

    def test_dom_or_dow(self) -> None:
        # 1st of month or Monday
        expr = "0 0 1 * 1"
        monday = datetime(2026, 9, 14, 0, 0)
        first = datetime(2026, 9, 1, 0, 0)
        other = datetime(2026, 9, 2, 0, 0)
        self.assertTrue(cron_matches(expr, monday))
        self.assertTrue(cron_matches(expr, first))
        self.assertFalse(cron_matches(expr, other))

    def test_rejects_bad_expr(self) -> None:
        with self.assertRaises(ValueError):
            parse_cron("0 6 * *")
        with self.assertRaises(ValueError):
            parse_cron("60 0 * * *")


if __name__ == "__main__":
    unittest.main()
