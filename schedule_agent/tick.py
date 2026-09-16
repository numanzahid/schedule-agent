from __future__ import annotations

from datetime import datetime
from typing import Any

from schedule_agent.cron import cron_matches, floor_minute, minutes_between
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
    run_at = parse_iso(job["schedule"]["runAt"])
    return now >= run_at


def _cron_due(job: dict[str, Any], now: datetime) -> bool:
    expr = job["schedule"]["expr"]
    now_min = floor_minute(now)
    last_raw = job.get("lastRun")
    last_run = parse_iso(last_raw) if last_raw else None
    if last_run and floor_minute(last_run) == now_min:
        return False
    if cron_matches(expr, now_min):
        return True
    if last_run is None:
        return False
    start = floor_minute(last_run)
    from datetime import timedelta

    for minute in minutes_between(start + timedelta(minutes=1), now_min):
        if cron_matches(expr, minute):
            return True
    return False
