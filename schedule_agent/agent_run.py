from __future__ import annotations

import fcntl
import os
import signal
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


def run_job(job: dict, dry_run: bool = False, *, lock_held: bool = False) -> tuple[int, str | None]:
    job_id = job["id"]
    cmd = build_agent_cmd(job)
    if dry_run:
        print(shlex_join(cmd))
        return 0, None

    if lock_held:
        return _exec(job, cmd)

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
    # The child writes directly to the log: no pipe buffering or lost timeout output.
    with path.open("a+", encoding="utf-8", errors="replace") as log:
        log.write(header)
        log.flush()
        output_start = log.tell()
        try:
            with subprocess.Popen(
                cmd,
                cwd=job["workspace"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            ) as proc:
                try:
                    exit_code = proc.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    # Agents can launch child processes; stop the whole job on timeout.
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    exit_code = 124
        except OSError as exc:
            exit_code = 2
            log.write(f"ERROR: {exc}\n")
            log.flush()
        output_end = log.seek(0, os.SEEK_END)
        log.seek(output_start)
        spawned = None
        last_char = ""
        # Scan incrementally to avoid holding a potentially large agent log in memory.
        while log.tell() < output_end:
            line = log.readline()
            if not line:
                break
            if should_spawn(job) and spawned is None:
                spawned = parse_spawned_id(line)
            last_char = line[-1:]
        log.seek(0, os.SEEK_END)
        if last_char and last_char != "\n":
            log.write("\n")
        if exit_code == 124:
            log.write(f"ERROR: timed out after {timeout_s}s\n")
        if spawned:
            log.write(f"spawned_chat_id={spawned}\n")
        duration = int(time.time() - started)
        log.write(f"===== {now_iso()} END exit={exit_code} duration={duration}s =====\n")
    return exit_code, spawned
