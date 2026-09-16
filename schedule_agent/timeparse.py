from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timedelta


class TimeError(Exception):
    pass


def parse_timeout(value: str) -> int:
    raw = value.strip().lower()
    match = re.fullmatch(r"(\d+)([smhd])?", raw)
    if not match:
        raise TimeError("timeout must look like 30s, 15m, 2h, or 1d")
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    seconds = amount * multiplier
    if seconds < 1:
        raise TimeError("timeout must be at least 1 second")
    return seconds


def parse_at(value: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now().astimezone()
    text = value.strip()
    if text.lower() == "now":
        return now

    rel = re.fullmatch(
        r"now\s*\+\s*(\d+)\s*(minutes?|minute|mins?|min|hours?|hour|hrs?|hr|days?|day)",
        text,
        flags=re.IGNORECASE,
    )
    if rel:
        amount = int(rel.group(1))
        unit = rel.group(2).lower()
        if unit.startswith("min"):
            delta = timedelta(minutes=amount)
        elif unit.startswith("h"):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return now + delta

    iso_text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        return dt.astimezone(now.tzinfo)
    except ValueError:
        pass

    date_bin = shutil.which("date")
    if date_bin:
        try:
            proc = subprocess.run(
                [date_bin, "-d", text, "--iso-8601=seconds"],
                check=True,
                capture_output=True,
                text=True,
            )
            parsed = datetime.fromisoformat(proc.stdout.strip())
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=now.tzinfo)
            return parsed.astimezone(now.tzinfo)
        except (subprocess.CalledProcessError, ValueError):
            pass

    raise TimeError(
        f"cannot parse time: {value!r}. Try ISO-8601 or 'now + 2 hours'"
    )


def format_schedule(job: dict) -> str:
    sched = job.get("schedule") or {}
    kind = sched.get("type")
    if kind == "cron":
        return f"cron {sched.get('expr', '')}".strip()
    if kind == "at":
        return f"at {sched.get('runAt', '')}".strip()
    return "unknown"
