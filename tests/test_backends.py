from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from schedule_agent.backends import build_cmd, normalize_backend


class BackendTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_backend("cursor-cli"), "cursor")
        self.assertEqual(normalize_backend("codex"), "codex")
        self.assertEqual(normalize_backend(None), "cursor")

    def test_cursor_cmd(self) -> None:
        cmd = build_cmd(
            {
                "id": "j",
                "backend": "cursor",
                "chatId": "abc",
                "workspace": "/tmp/ws",
                "prompt": "hello",
            }
        )
        self.assertIn("--resume=abc", cmd)
        self.assertIn("--print", cmd)
        self.assertIn("--force", cmd)

    def test_codex_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["XDG_STATE_HOME"] = tmp
            cmd = build_cmd(
                {
                    "id": "j",
                    "backend": "codex",
                    "chatId": "sess-1",
                    "workspace": "/tmp/ws",
                    "prompt": "hello",
                    "model": "gpt-test",
                }
            )
        self.assertEqual(cmd[1], "exec")
        self.assertIn("resume", cmd)
        self.assertIn("sess-1", cmd)
        self.assertIn("-C", cmd)
        self.assertIn("/tmp/ws", cmd)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", cmd)
        self.assertIn("gpt-test", cmd)

    def tearDown(self) -> None:
        os.environ.pop("SCHEDULE_AGENT_BIN", None)
        os.environ.pop("SCHEDULE_CODEX_BIN", None)
        os.environ.pop("XDG_STATE_HOME", None)


if __name__ == "__main__":
    unittest.main()
