from __future__ import annotations

import os
import shutil
from pathlib import Path

from schedule_agent.config import log_dir

BACKENDS = ("cursor", "codex")
DEFAULT_BACKEND = "cursor"


class BackendError(Exception):
    pass


def normalize_backend(value: str | None) -> str:
    raw = (value or DEFAULT_BACKEND).strip().lower()
    if raw in {"cursor", "cursor-cli", "agent"}:
        return "cursor"
    if raw == "codex":
        return "codex"
    raise BackendError(f"unknown backend: {value!r} (supported: cursor, codex)")


def _resolve_bin(env_name: str, name: str) -> Path:
    env = os.environ.get(env_name)
    if env:
        return Path(env)
    local = Path.home() / ".local/bin" / name
    if local.exists():
        return local
    found = shutil.which(name)
    if found:
        return Path(found)
    return Path(name)


def cursor_bin() -> Path:
    return _resolve_bin("SCHEDULE_AGENT_BIN", "agent")


def codex_bin() -> Path:
    return _resolve_bin("SCHEDULE_CODEX_BIN", "codex")


def bin_exists(path: Path) -> bool:
    if path.exists():
        return True
    return shutil.which(str(path)) is not None or shutil.which(path.name) is not None


def build_cmd(job: dict) -> list[str]:
    backend = normalize_backend(job.get("backend"))
    if backend == "codex":
        return _codex_cmd(job)
    return _cursor_cmd(job)


def _cursor_cmd(job: dict) -> list[str]:
    resolved = str(cursor_bin())
    cmd = [
        resolved,
        f"--workspace={job['workspace']}",
        f"--resume={job['chatId']}",
        "-p",
        job["prompt"],
        "--print",
        "--output-format",
        "text",
        "--force",
        "--trust",
    ]
    model = job.get("model")
    if model:
        cmd.extend(["--model", model])
    return cmd


def _codex_cmd(job: dict) -> list[str]:
    resolved = str(codex_bin())
    cmd = [
        resolved,
        "exec",
        "-C",
        job["workspace"],
        "--skip-git-repo-check",
        "--color",
        "never",
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    model = job.get("model")
    if model:
        cmd.extend(["-m", model])
    last_file = log_dir() / f"{job['id']}.last.txt"
    cmd.extend(["-o", str(last_file)])
    cmd.extend(["resume", job["chatId"], job["prompt"]])
    return cmd
