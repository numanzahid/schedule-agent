from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from schedule_agent.config import agent_bin, default_path, ensure_dirs, log_dir
from schedule_agent.jobs import lock_path_for, now_iso
from schedule_agent.timeparse import parse_timeout


SKIP_EXIT = 4


class RunError(Exception):
    def __init__(self, message: str, exit_code: int = 3):
        super().__init__(message)
        self.exit_code = exit_code


@contextmanager
def job_lock(job_id: str) -> Iterator[bool]:
    ensure_dirs()
    path = lock_path_for(job_id)
    path.touch(exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def log_path(job_id: str) -> Path:
    return log_dir() / f"{job_id}.log"


def build_agent_cmd(job: dict, extra_env: dict[str, str] | None = None) -> list[str]:
    binary = str(agent_bin())
    if binary != "agent" and not Path(binary).exists() and shutil.which("agent") is None:
        raise RunError(f"agent CLI not found (looked for {binary})", exit_code=2)
    resolved = binary if Path(binary).exists() else (shutil.which("agent") or binary)
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


def run_job(job: dict, dry_run: bool = False) -> int:
    job_id = job["id"]
    cmd = build_agent_cmd(job)
    if dry_run:
        print(" ".join(shlex_join(cmd)))
        return 0

    with job_lock(job_id) as acquired:
        if not acquired:
            print(f"SKIP: {job_id} already running")
            return SKIP_EXIT
        return _exec(job, cmd)


def shlex_join(cmd: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in cmd)


def _exec(job: dict, cmd: list[str]) -> int:
    job_id = job["id"]
    timeout_s = parse_timeout(str(job.get("timeout") or "30m"))
    path = log_path(job_id)
    ensure_dirs()
    started = time.time()
    header = (
        f"===== {now_iso()} START job={job_id} "
        f"chat={job['chatId']} workspace={job['workspace']} =====\n"
        f"cmd: {shlex_join(cmd)}\n"
    )
    env = os.environ.copy()
    env["PATH"] = default_path()
    env["HOME"] = str(Path.home())
    env["LANG"] = env.get("LANG") or "C.UTF-8"
    with path.open("a", encoding="utf-8") as log:
        log.write(header)
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=job["workspace"],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write(f"ERROR: timed out after {timeout_s}s\n")
        except FileNotFoundError as exc:
            exit_code = 2
            log.write(f"ERROR: {exc}\n")
        duration = int(time.time() - started)
        log.write(f"===== {now_iso()} END exit={exit_code} duration={duration}s =====\n")
    return exit_code
