from __future__ import annotations

import fcntl
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from schedule_agent.config import ensure_dirs, jobs_lock_path, jobs_path

JOB_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$")


class JobError(Exception):
    pass


def now_iso(now: datetime | None = None) -> str:
    stamp = now or datetime.now().astimezone()
    return stamp.isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


@contextmanager
def registry_lock() -> Iterator[None]:
    ensure_dirs()
    lock_file = jobs_lock_path()
    lock_file.touch(exist_ok=True)
    with lock_file.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def empty_registry() -> dict[str, Any]:
    return {"version": 1, "jobs": {}}


def load_registry() -> dict[str, Any]:
    path = jobs_path()
    if not path.exists():
        return empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JobError(f"corrupt jobs file: {path}") from exc
    if not isinstance(data, dict) or "jobs" not in data:
        raise JobError(f"invalid jobs file: {path}")
    if not isinstance(data["jobs"], dict):
        raise JobError(f"invalid jobs file: {path}")
    data.setdefault("version", 1)
    return data


def save_registry(data: dict[str, Any]) -> None:
    ensure_dirs()
    path = jobs_path()
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2, sort_keys=False) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.match(job_id):
        raise JobError(
            "job name must be 1-63 chars, start with a letter or number, "
            "and contain only letters, numbers, hyphens, or underscores"
        )
    return job_id


def new_job_id() -> str:
    return "job-" + uuid.uuid4().hex[:8]


def get_job(data: dict[str, Any], job_id: str) -> dict[str, Any]:
    job = data.get("jobs", {}).get(job_id)
    if not job:
        raise JobError(f"unknown job: {job_id}")
    return job


def upsert_job(job: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    with registry_lock():
        data = load_registry()
        job_id = job["id"]
        if job_id in data["jobs"] and not replace:
            raise JobError(f"job already exists: {job_id} (pass --replace to overwrite)")
        data["jobs"][job_id] = job
        save_registry(data)
        return job


def delete_job(job_id: str) -> dict[str, Any]:
    with registry_lock():
        data = load_registry()
        job = get_job(data, job_id)
        del data["jobs"][job_id]
        save_registry(data)
        return job


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    with registry_lock():
        data = load_registry()
        job = get_job(data, job_id)
        job.update(fields)
        data["jobs"][job_id] = job
        save_registry(data)
        return job


def set_enabled(job_id: str, enabled: bool) -> dict[str, Any]:
    return update_job(job_id, enabled=enabled)


def list_jobs() -> list[dict[str, Any]]:
    data = load_registry()
    jobs = list(data["jobs"].values())
    jobs.sort(key=lambda row: row.get("createdAt") or "")
    return jobs


def lock_path_for(job_id: str) -> Path:
    from schedule_agent.config import lock_dir

    return lock_dir() / f"{job_id}.lock"
