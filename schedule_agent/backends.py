from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from schedule_agent.config import log_dir

BACKENDS = ("cursor", "codex", "claude")
DEFAULT_BACKEND = "cursor"


class BackendError(Exception):
    pass


def normalize_backend(value: str | None) -> str:
    raw = (value or DEFAULT_BACKEND).strip().lower()
    if raw in {"cursor", "cursor-cli", "agent"}:
        return "cursor"
    if raw in {"codex", "claude"}:
        return raw
    if raw == "claude-code":
        return "claude"
    raise BackendError(f"unknown backend: {value!r} (supported: {', '.join(BACKENDS)})")


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


def claude_bin() -> Path:
    return _resolve_bin("SCHEDULE_CLAUDE_BIN", "claude")


def bin_exists(path: Path) -> bool:
    return shutil.which(str(path)) is not None


def claude_auth_status() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [str(claude_bin()), "auth", "status", "--json"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not check Claude authentication: {exc}"
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        data = None
    if proc.returncode == 0 and isinstance(data, dict) and data.get("loggedIn") is True:
        return True, "authenticated; method: " + str(data.get("authMethod") or "configured provider")
    return False, "Claude is not authenticated or auth status failed; run: claude auth login"


def extra_args(job: dict) -> list[str]:
    raw = job.get("extraArgs") or []
    return [str(part) for part in raw]


def should_spawn(job: dict) -> bool:
    if (job.get("spawn") or "") == "each":
        return True
    return not bool(job.get("chatId"))


def build_cmd(job: dict) -> list[str]:
    backend = normalize_backend(job.get("backend"))
    if backend == "codex":
        return _codex_cmd(job)
    if backend == "claude":
        return _claude_cmd(job)
    return _cursor_cmd(job)


def _cursor_cmd(job: dict) -> list[str]:
    resolved = str(cursor_bin())
    spawn = should_spawn(job)
    cmd = [
        resolved,
        f"--workspace={job['workspace']}",
        "-p",
        job["prompt"],
        "--print",
        "--output-format",
        "json" if spawn else "text",
        "--force",
        "--trust",
    ]
    if not spawn:
        cmd.insert(2, f"--resume={job['chatId']}")
    model = job.get("model")
    if model:
        cmd.extend(["--model", model])
    cmd.extend(extra_args(job))
    return cmd


def _codex_cmd(job: dict) -> list[str]:
    resolved = str(codex_bin())
    spawn = should_spawn(job)
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
    if spawn:
        cmd.append("--json")
    model = job.get("model")
    if model:
        cmd.extend(["-m", model])
    last_file = log_dir() / f"{job['id']}.last.txt"
    cmd.extend(["-o", str(last_file)])
    cmd.extend(extra_args(job))
    if spawn:
        cmd.append(job["prompt"])
    else:
        cmd.extend(["resume", job["chatId"], job["prompt"]])
    return cmd


def _claude_cmd(job: dict) -> list[str]:
    # cwd is supplied by the runner. Stream JSON emits the session ID at startup,
    # so a failed or timed-out first attempt can still be resumed on retry.
    cmd = [
        str(claude_bin()), "--print", "--output-format", "stream-json",
        "--verbose", "--dangerously-skip-permissions",
    ]
    if not should_spawn(job):
        cmd.extend(["--resume", job["chatId"]])
    if job.get("model"):
        cmd.extend(["--model", job["model"]])
    cmd.extend(extra_args(job))
    cmd.extend(["--", job["prompt"]])
    return cmd


def parse_spawned_id(output: str) -> str | None:
    for line in output.splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        for key in ("session_id", "thread_id"):
            value = data.get(key)
            if value:
                return str(value)
        if data.get("type") == "thread.started" and data.get("thread_id"):
            return str(data["thread_id"])
        payload = data.get("payload")
        if isinstance(payload, dict) and data.get("type") == "session_meta" and payload.get("id"):
            return str(payload["id"])
    return None
