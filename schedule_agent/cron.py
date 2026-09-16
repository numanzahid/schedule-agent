from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

DOW_NAMES = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}


def _sub_names(field: str, names: dict[str, int]) -> str:
    out = field.lower()
    for name, value in names.items():
        out = re.sub(rf"\b{name}\b", str(value), out)
    return out


def expand_field(field: str, min_v: int, max_v: int, names: dict[str, int] | None = None) -> set[int]:
    raw = field.strip()
    if names:
        raw = _sub_names(raw, names)
    values: set[int] = set()
    if raw == "*":
        return set(range(min_v, max_v + 1))
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron field item")
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError(f"invalid cron step: {part}")
            part = base
        if part == "*":
            start, end = min_v, max_v
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < min_v or end > max_v or start > end:
            raise ValueError(f"cron field out of range: {field}")
        values.update(range(start, end + 1, step))
    if max_v == 7:
        if 7 in values:
            values.add(0)
            values.discard(7)
    return values


def parse_cron(expr: str) -> tuple[str, str, str, str, str]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron expression must have 5 fields: minute hour dom month dow")
    minute, hour, dom, month, dow = parts
    expand_field(minute, 0, 59)
    expand_field(hour, 0, 23)
    expand_field(dom, 1, 31)
    expand_field(month, 1, 12, MONTH_NAMES)
    expand_field(dow, 0, 7, DOW_NAMES)
    return minute, hour, dom, month, dow


def cron_dow(dt: datetime) -> int:
    # Python Monday=0 .. Sunday=6  ->  cron Sunday=0 .. Saturday=6
    return (dt.weekday() + 1) % 7


def cron_matches(expr: str, dt: datetime) -> bool:
    minute_f, hour_f, dom_f, month_f, dow_f = parse_cron(expr)
    minutes = expand_field(minute_f, 0, 59)
    hours = expand_field(hour_f, 0, 23)
    doms = expand_field(dom_f, 1, 31)
    months = expand_field(month_f, 1, 12, MONTH_NAMES)
    dows = expand_field(dow_f, 0, 7, DOW_NAMES)

    if dt.minute not in minutes or dt.hour not in hours or dt.month not in months:
        return False

    dom_star = dom_f == "*"
    dow_star = dow_f == "*"
    if dom_star and dow_star:
        return True
    if not dom_star and not dow_star:
        return dt.day in doms or cron_dow(dt) in dows
    if not dom_star:
        return dt.day in doms
    return cron_dow(dt) in dows


def floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def minutes_between(start: datetime, end: datetime, limit_hours: int = 24) -> Iterable[datetime]:
    start = floor_minute(start)
    end = floor_minute(end)
    if end < start:
        return
    max_span = timedelta(hours=limit_hours)
    if end - start > max_span:
        start = end - max_span
    current = start
    while current <= end:
        yield current
        current += timedelta(minutes=1)
