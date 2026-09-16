from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from schedule_agent.cli import main
from schedule_agent.jobs import list_jobs, load_registry
from schedule_agent.timeparse import parse_at, parse_timeout


class TimeParseTests(unittest.TestCase):
    def test_timeout_units(self) -> None:
        self.assertEqual(parse_timeout("30s"), 30)
        self.assertEqual(parse_timeout("15m"), 900)
        self.assertEqual(parse_timeout("2h"), 7200)

    def test_now_plus_hours(self) -> None:
        now = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
        got = parse_at("now + 2 hours", now=now)
        self.assertEqual(got, now + timedelta(hours=2))


class CliAddTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Path(self.tmp.name) / "config"
        self.state = Path(self.tmp.name) / "state"
        os.environ["XDG_CONFIG_HOME"] = str(self.config)
        os.environ["XDG_STATE_HOME"] = str(self.state)
        self.workspace = Path(self.tmp.name) / "ws"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop("XDG_STATE_HOME", None)

    def test_add_cron_and_list(self) -> None:
        code = main(
            [
                "add",
                "--chat-id",
                "880826cf-1a45-4e64-a06f-fed5f23f9d0f",
                "--workspace",
                str(self.workspace),
                "--name",
                "daily",
                "--cron",
                "0 6 * * *",
                "--prompt",
                "Ping. Do not ask questions; complete autonomously.",
            ]
        )
        self.assertEqual(code, 0)
        jobs = list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "daily")
        self.assertEqual(jobs[0]["backend"], "cursor")
        self.assertEqual(jobs[0]["schedule"]["expr"], "0 6 * * *")
        self.assertEqual(main(["list", "--json"]), 0)
        self.assertEqual(main(["remove", "daily"]), 0)
        self.assertEqual(load_registry()["jobs"], {})

    def test_add_codex_dry_run(self) -> None:
        os.environ["SCHEDULE_CODEX_BIN"] = "/tmp/fake-codex"
        code = main(
            [
                "add",
                "--backend",
                "codex",
                "--chat-id",
                "sess-1",
                "--workspace",
                str(self.workspace),
                "--name",
                "cx",
                "--at",
                "now + 1 hour",
                "--prompt",
                "Ping.",
                "--dry-run",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(load_registry()["jobs"], {})
        os.environ.pop("SCHEDULE_CODEX_BIN", None)

    def test_add_rejects_both_schedules(self) -> None:
        code = main(
            [
                "add",
                "--chat-id",
                "abc",
                "--workspace",
                str(self.workspace),
                "--cron",
                "0 6 * * *",
                "--at",
                "now + 1 hour",
                "--prompt",
                "x",
            ]
        )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
