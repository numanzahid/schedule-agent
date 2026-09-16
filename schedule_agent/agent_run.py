from __future__ import annotations

import fcntl
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from schedule_agent.backends import BackendError, build_cmd, parse_spawned_id, should_spawn
from schedule_agent.config import default_path, ensure_dirs, log_dir
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
    try:
        return build_cmd(job)
    except BackendError as exc:
        raise RunError(str(exc), exit_code=2) from exc


def run_job(job: dict, dry_run: bool = False) -> tuple[int, str | None]:
    job_id = job["id"]
    cmd = build_agent_cmd(job)
    if dry_run:
        print(shlex_join(cmd))
        return 0, None

    with job_lock(job_id) as acquired:
        if not acquired:
            print(f"SKIP: {job_id} already running")
            return SKIP_EXIT, None
        return _exec(job, cmd)


def shlex_join(cmd: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in cmd)


def _exec(job: dict, cmd: list[str]) -> tuple[int, str | None]:
    job_id = job["id"]
    timeout_s = parse_timeout(str(job.get("timeout") or "30m"))
    path = log_path(job_id)
    ensure_dirs()
    started = time.time()
    backend = job.get("backend") or "cursor"
    chat = job.get("chatId") or "(new)"
    header = (
        f"===== {now_iso()} START job={job_id} backend={backend} "
        f"chat={chat} spawn={should_spawn(job)} workspace={job['workspace']} =====\n"
        f"cmd: {shlex_join(cmd)}\n"
    )
    env = os.environ.copy()
    env["PATH"] = default_path()
    env["HOME"] = str(Path.home())
    env["LANG"] = env.get("LANG") or "C.UTF-8"
    output = ""
    with path.open("a", encoding="utf-8") as log:
        log.write(header)
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=job["workspace"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
                text=True,
            )
            exit_code = proc.returncode
            output = proc.stdout or ""
            log.write(output)
            if output and not output.endswith("\n"):
                log.write("\n")
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            if output:
                log.write(output)
            log.write(f"ERROR: timed out after {timeout_s}s\n")
        except FileNotFoundError as exc:
            exit_code = 2
            log.write(f"ERROR: {exc}\n")
        spawned = parse_spawned_id(output) if should_spawn(job) else None
        if spawned:
            log.write(f"spawned_chat_id={spawned}\n")
        duration = int(time.time() - started)
        log.write(f"===== {now_iso()} END exit={exit_code} duration={duration}s =====\n")
    return exit_code, spawned
