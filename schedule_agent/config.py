from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "schedule-agent"
TIMER_UNIT = "cursor-schedule.timer"
SERVICE_UNIT = "cursor-schedule.service"


def _xdg_home(env_name: str, default_sub: Path) -> Path:
    raw = os.environ.get(env_name)
    if raw:
        return Path(raw).expanduser()
    return Path.home() / default_sub


def config_dir() -> Path:
    return _xdg_home("XDG_CONFIG_HOME", Path(".config")) / APP_NAME


def state_dir() -> Path:
    return _xdg_home("XDG_STATE_HOME", Path(".local/state")) / APP_NAME


def jobs_path() -> Path:
    return config_dir() / "jobs.json"


def jobs_lock_path() -> Path:
    return config_dir() / "jobs.lock"


def log_dir() -> Path:
    return state_dir() / "logs"


def lock_dir() -> Path:
    return state_dir() / "locks"


def systemd_user_dir() -> Path:
    return Path.home() / ".config/systemd/user"


def ensure_dirs() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
    lock_dir().mkdir(parents=True, exist_ok=True)


def agent_bin() -> Path:
    env = os.environ.get("SCHEDULE_AGENT_BIN")
    if env:
        return Path(env)
    local = Path.home() / ".local/bin/agent"
    if local.exists():
        return local
    return Path("agent")


def default_path() -> str:
    extra = str(Path.home() / ".local/bin")
    current = os.environ.get("PATH", "/usr/bin:/bin")
    if extra not in current.split(":"):
        return extra + ":" + current
    return current
