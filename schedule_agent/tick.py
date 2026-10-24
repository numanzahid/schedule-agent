from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from schedule_agent.cron import cron_matches, cron_occurs_between, floor_minute
from schedule_agent.jobs import parse_iso


def job_is_due(job: dict[str, Any], now: datetime) -> bool:
    if not job.get("enabled", True):
        return False
    sched = job.get("schedule") or {}
    kind = sched.get("type")
    if kind == "at":
        return _at_due(job, now)
    if kind == "cron":
        return _cron_due(job, now)
    return False


def _at_due(job: dict[str, Any], now: datetime) -> bool:
    if job.get("lastStatus") == "ok":
        return False
    retry_at = job.get("nextRetryAt")
    if retry_at and now < parse_iso(retry_at):
        return False
    run_at = parse_iso(job["schedule"]["runAt"])
    return now >= run_at


def _cron_due(job: dict[str, Any], now: datetime) -> bool:
    expr = job["schedule"]["expr"]
    now_min = floor_minute(now)
    last_raw = job.get("lastRun")
    last_run = parse_iso(last_raw) if last_raw else None
    if last_run:
        start = floor_minute(last_run) + timedelta(minutes=1)
    elif job.get("createdAt"):
        created = parse_iso(job["createdAt"])
        start = floor_minute(created)
        if created > start:
            start += timedelta(minutes=1)
    else:
        # Legacy registries without a creation timestamp have no recovery baseline.
        return cron_matches(expr, now_min)
    return cron_occurs_between(expr, start, now_min)
