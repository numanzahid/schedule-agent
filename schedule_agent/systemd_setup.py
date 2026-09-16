from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from schedule_agent.config import SERVICE_UNIT, TIMER_UNIT, systemd_user_dir

SERVICE_BODY = """[Unit]
Description=schedule-agent dispatcher tick
After=default.target

[Service]
Type=oneshot
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/schedule-agent tick
Nice=10
"""

TIMER_BODY = """[Unit]
Description=schedule-agent dispatcher (once per minute)

[Timer]
OnCalendar=minutely
Persistent=true
AccuracySec=10s
Unit=cursor-schedule.service

[Install]
WantedBy=timers.target
"""


class SetupError(Exception):
    pass


def write_units() -> tuple[Path, Path]:
    target = systemd_user_dir()
    target.mkdir(parents=True, exist_ok=True)
    service = target / SERVICE_UNIT
    timer = target / TIMER_UNIT
    service.write_text(SERVICE_BODY, encoding="utf-8")
    timer.write_text(TIMER_BODY, encoding="utf-8")
    return service, timer


def setup_timer() -> dict[str, str]:
    service, timer = write_units()
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise SetupError("systemctl not found; systemd user timers are required")
    commands = [
        [systemctl, "--user", "daemon-reload"],
        [systemctl, "--user", "enable", "--now", TIMER_UNIT],
    ]
    for cmd in commands:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise SetupError(f"{' '.join(cmd)} failed: {detail}")
    return {"service": str(service), "timer": str(timer)}


def timer_is_enabled() -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    proc = subprocess.run(
        [systemctl, "--user", "is-enabled", TIMER_UNIT],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() in {"enabled", "static", "generated"}


def timer_is_active() -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    proc = subprocess.run(
        [systemctl, "--user", "is-active", TIMER_UNIT],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "active"


def linger_enabled() -> bool | None:
    loginctl = shutil.which("loginctl")
    if not loginctl:
        return None
    import os

    proc = subprocess.run(
        [loginctl, "show-user", os.environ.get("USER", ""), "-p", "Linger"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().endswith("=yes")
