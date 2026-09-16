from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from schedule_agent import __version__
from schedule_agent.agent_run import SKIP_EXIT, log_path, run_job, shlex_join, build_agent_cmd
from schedule_agent.backends import (
    BackendError,
    bin_exists,
    codex_bin,
    cursor_bin,
    normalize_backend,
)
from schedule_agent.chats import ChatError, chats_for_cwd, resolve_workspace
from schedule_agent.config import jobs_path
from schedule_agent.cron import parse_cron
from schedule_agent.jobs import (
    JobError,
    delete_job,
    list_jobs,
    load_registry,
    new_job_id,
    now_iso,
    set_enabled,
    update_job,
    upsert_job,
    validate_job_id,
)
from schedule_agent.systemd_setup import (
    SetupError,
    linger_enabled,
    setup_timer,
    timer_is_active,
    timer_is_enabled,
)
from schedule_agent.tick import job_is_due
from schedule_agent.timeparse import TimeError, format_schedule, parse_at, parse_timeout


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (JobError, ChatError, TimeError, SetupError, BackendError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schedule-agent",
        description="Schedule prompts into an existing agent chat (Cursor CLI and Codex).",
    )
    parser.add_argument("--version", action="version", version=f"schedule-agent {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="create a one-shot or recurring job")
    add.add_argument(
        "--backend",
        default="cursor",
        help="agent backend: cursor or codex (default: cursor)",
    )
    add.add_argument("--chat-id", required=True, help="chat / thread id to resume")
    add.add_argument("--prompt", help="prompt posted into the resumed chat")
    add.add_argument("--prompt-file", type=Path, help="read prompt from a file")
    add.add_argument("--workspace", help="workspace path (default: chat meta.json cwd)")
    add.add_argument("--name", help="stable job id (default: generated)")
    add.add_argument("--cron", help='5-field cron, e.g. "0 6 * * *"')
    add.add_argument("--at", dest="at_when", help='one-shot time, e.g. "now + 2 hours"')
    add.add_argument("--timeout", default="30m", help="agent timeout (default: 30m)")
    add.add_argument("--model", help="optional --model passed to agent")
    add.add_argument("--replace", action="store_true", help="overwrite an existing job id")
    add.add_argument("--json", action="store_true", help="print the job as JSON")
    add.add_argument("--dry-run", action="store_true", help="print the agent command and do not save")
    add.set_defaults(func=cmd_add)

    listing = sub.add_parser("list", help="list jobs")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="show one job")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    remove = sub.add_parser("remove", help="delete a job")
    remove.add_argument("name")
    remove.add_argument("--json", action="store_true")
    remove.set_defaults(func=cmd_remove)

    enable = sub.add_parser("enable", help="enable a job")
    enable.add_argument("name")
    enable.set_defaults(func=lambda a: cmd_toggle(a, True))

    disable = sub.add_parser("disable", help="disable a job")
    disable.add_argument("name")
    disable.set_defaults(func=lambda a: cmd_toggle(a, False))

    run = sub.add_parser("run", help="run a job now")
    run.add_argument("name")
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    tick = sub.add_parser("tick", help="run jobs that are due (used by systemd)")
    tick.add_argument("--dry-run", action="store_true")
    tick.set_defaults(func=cmd_tick)

    validate = sub.add_parser("validate", help="check agent, timer, and optional chat id")
    validate.add_argument("--chat-id")
    validate.add_argument("--workspace")
    validate.add_argument(
        "--backend",
        default="cursor",
        help="agent backend to check with --chat-id (default: cursor)",
    )
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=cmd_validate)

    chats = sub.add_parser("chats", help="list local chats")
    chats.add_argument("--cwd", help="limit to chats whose recorded cwd matches")
    chats.add_argument(
        "--backend",
        default="cursor",
        help="cursor, codex, or all (default: cursor)",
    )
    chats.add_argument("--json", action="store_true")
    chats.set_defaults(func=cmd_chats)

    log = sub.add_parser("log", help="print a job log")
    log.add_argument("name")
    log.add_argument("-n", "--lines", type=int, default=80)
    log.set_defaults(func=cmd_log)

    setup = sub.add_parser("setup", help="install the two systemd user units and enable the timer")
    setup.set_defaults(func=cmd_setup)

    return parser


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt and args.prompt_file:
        raise JobError("use either --prompt or --prompt-file, not both")
    if args.prompt_file:
        path = args.prompt_file.expanduser()
        if not path.is_file():
            raise JobError(f"prompt file not found: {path}")
        text = path.read_text(encoding="utf-8").strip()
    elif args.prompt:
        text = args.prompt.strip()
    else:
        raise JobError("--prompt or --prompt-file is required")
    if not text:
        raise JobError("prompt is empty")
    return text


def cmd_add(args: argparse.Namespace) -> int:
    if bool(args.cron) == bool(args.at_when):
        raise JobError("provide exactly one of --cron or --at")
    parse_timeout(args.timeout)
    prompt = read_prompt(args)
    backend = normalize_backend(args.backend)
    workspace = str(resolve_workspace(args.chat_id, args.workspace, backend=backend))
    job_id = validate_job_id(args.name) if args.name else new_job_id()
    created = now_iso()
    if args.cron:
        parse_cron(args.cron)
        schedule = {"type": "cron", "expr": args.cron}
    else:
        when = parse_at(args.at_when)
        schedule = {"type": "at", "runAt": when.isoformat(timespec="seconds")}
    job = {
        "id": job_id,
        "backend": backend,
        "chatId": args.chat_id,
        "workspace": workspace,
        "prompt": prompt,
        "schedule": schedule,
        "timeout": args.timeout,
        "model": args.model,
        "enabled": True,
        "createdAt": created,
        "lastRun": None,
        "lastStatus": None,
        "lastExit": None,
    }
    if args.dry_run:
        print(shlex_join(build_agent_cmd(job)))
        if args.json:
            print(json.dumps(job, indent=2))
        return 0
    saved = upsert_job(job, replace=args.replace)
    if not timer_is_enabled():
        print("note: dispatcher timer is not enabled. run: schedule-agent setup", file=sys.stderr)
    if args.json:
        print(json.dumps(saved, indent=2))
    else:
        print(f"added {saved['id']}  {format_schedule(saved)}")
        print(f"backend {saved.get('backend') or 'cursor'}")
        print(f"chat {saved['chatId']}")
        print(f"workspace {saved['workspace']}")
        if schedule["type"] == "cron":
            print("runs when the dispatcher timer fires on a matching minute")
        else:
            print(f"one-shot at {schedule['runAt']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    jobs = list_jobs()
    if args.json:
        print(json.dumps(jobs, indent=2))
        return 0
    if not jobs:
        print("no jobs")
        return 0
    rows = [
        (
            job["id"],
            job.get("backend") or "cursor",
            "on" if job.get("enabled", True) else "off",
            format_schedule(job),
            (job.get("lastStatus") or "-"),
            (job.get("lastRun") or "-"),
        )
        for job in jobs
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(6)]
    headers = ["NAME", "BACKEND", "ON", "SCHEDULE", "LAST", "LAST_RUN"]
    for i, header in enumerate(headers):
        widths[i] = max(widths[i], len(header))
    print("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(6)))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    job = _require_job(args.name)
    print(json.dumps(job, indent=2))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    job = delete_job(args.name)
    if args.json:
        print(json.dumps(job, indent=2))
    else:
        print(f"removed {job['id']}")
    return 0


def cmd_toggle(args: argparse.Namespace, enabled: bool) -> int:
    job = set_enabled(args.name, enabled)
    state = "enabled" if enabled else "disabled"
    print(f"{state} {job['id']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    job = _require_job(args.name)
    if args.dry_run:
        return run_job(job, dry_run=True)
    exit_code = run_job(job, dry_run=False)
    if exit_code == SKIP_EXIT:
        return 0
    _record_run(job["id"], exit_code)
    return 0 if exit_code == 0 else 3


def cmd_tick(args: argparse.Namespace) -> int:
    now = datetime.now().astimezone()
    due = [job for job in list_jobs() if job_is_due(job, now)]
    if args.dry_run:
        for job in due:
            print(job["id"])
        return 0
    for job in due:
        exit_code = run_job(job, dry_run=False)
        if exit_code == SKIP_EXIT:
            continue
        _record_run(job["id"], exit_code, complete_one_shot=True)
    return 0


def _record_run(job_id: str, exit_code: int, complete_one_shot: bool = False) -> None:
    status = "ok" if exit_code == 0 else "failed"
    fields: dict[str, Any] = {
        "lastRun": now_iso(),
        "lastStatus": status,
        "lastExit": exit_code,
    }
    if complete_one_shot:
        job = _require_job(job_id)
        if job.get("schedule", {}).get("type") == "at":
            fields["enabled"] = False
            if status == "ok":
                fields["completedAt"] = fields["lastRun"]
    update_job(job_id, **fields)


def cmd_validate(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {
        "ok": True,
        "version": __version__,
        "jobsFile": str(jobs_path()),
        "checks": [],
    }

    def check(name: str, ok: bool, detail: str) -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False

    requested = normalize_backend(getattr(args, "backend", "cursor"))
    cursor = cursor_bin()
    codex = codex_bin()
    if bin_exists(cursor):
        check("cursor", True, str(cursor))
    elif requested == "cursor":
        check("cursor", False, "Cursor CLI (agent) not found")
    else:
        report.setdefault("warnings", []).append("Cursor CLI not installed")
        check("cursor", True, "not installed")

    if bin_exists(codex):
        check("codex", True, str(codex))
    elif requested == "codex":
        check("codex", False, "Codex CLI not found")
    else:
        report.setdefault("warnings", []).append("Codex CLI not installed")
        check("codex", True, "not installed")
    systemctl = shutil.which("systemctl")
    if systemctl:
        check("systemctl", True, systemctl)
        check("timerEnabled", timer_is_enabled(), "cursor-schedule.timer" if timer_is_enabled() else TIMER_HINT)
        check("timerActive", timer_is_active(), "cursor-schedule.timer" if timer_is_active() else TIMER_HINT)
    else:
        check("systemctl", False, "systemctl not found")

    linger = linger_enabled()
    if linger is None:
        check("linger", True, "loginctl unavailable; skipped")
    else:
        check(
            "linger",
            True if linger else True,
            "yes" if linger else "no (jobs may not run while logged out; sudo loginctl enable-linger $USER once)",
        )
        if not linger:
            report.setdefault("warnings", []).append("linger is off")

    if args.chat_id:
        try:
            workspace = resolve_workspace(
                args.chat_id, args.workspace, backend=requested
            )
            check("chat", True, f"{requested} {args.chat_id} -> {workspace}")
        except ChatError as exc:
            check("chat", False, str(exc))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        state = "OK" if report["ok"] else "FAIL"
        print(f"schedule-agent {__version__}  {state}")
        for item in report["checks"]:
            mark = "ok" if item["ok"] else "FAIL"
            print(f"  [{mark}] {item['name']}: {item['detail']}")
        for warning in report.get("warnings") or []:
            print(f"  warning: {warning}")
    return 0 if report["ok"] else 2


TIMER_HINT = "run: schedule-agent setup"


def cmd_chats(args: argparse.Namespace) -> int:
    kind = (args.backend or "cursor").strip().lower()
    if kind == "all":
        rows = chats_for_cwd(args.cwd, "cursor") + chats_for_cwd(args.cwd, "codex")
        rows.sort(key=lambda row: row.get("updatedAt") or "", reverse=True)
    else:
        normalize_backend(kind)
        rows = chats_for_cwd(args.cwd, kind)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print(f"no chats found for backend {kind}")
        return 0
    for row in rows:
        cwd = row.get("cwd") or "-"
        backend = row.get("backend") or kind
        print(f"{backend}  {row['id']}  {row['title']}  {cwd}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    _require_job(args.name)
    path = log_path(args.name)
    if not path.exists():
        print(f"no log yet: {path}")
        return 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-args.lines :]:
        print(line)
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    result = setup_timer()
    print(f"wrote {result['service']}")
    print(f"wrote {result['timer']}")
    print(f"enabled {result['timer'].rsplit('/', 1)[-1]}")
    return 0


def _require_job(job_id: str) -> dict[str, Any]:
    data = load_registry()
    jobs = data.get("jobs") or {}
    if job_id not in jobs:
        raise JobError(f"unknown job: {job_id}")
    return jobs[job_id]
