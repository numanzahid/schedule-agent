# schedule-agent

Schedule a Cursor CLI or Codex prompt to run later. The job still runs after you close the IDE chat.

It can:

- resume an existing thread (`--chat-id`)
- start a new thread in a folder (`--new --workspace`)
- run once (`--at`) or on a cron (`--cron`)
- pass extra flags through to `agent` or `codex`

A `sleep` loop in an IDE terminal dies when that session ends. `crontab` and per-job systemd units also get messy. This tool stores jobs in JSON and uses **one** systemd user timer (once a minute, two unit files forever). Adding jobs does not create more systemd units. Several jobs can run at the same time; only the same job is skipped if it is already running.

```text
systemd user timer  (2 files, forever)
  -> schedule-agent tick
  -> Cursor CLI (`agent`) or Codex (`codex exec`)
       resume --chat-id  OR  spawn --new in --workspace
  -> process exits when the turn is done
  -> log + lastStatus  (and store a new chatId after --new)
```

## Supported agents

| Agent | Binary | Resume | Spawn |
|-------|--------|--------|-------|
| Cursor CLI | `agent` | `--resume=<id>` | `--workspace=<dir>` without `--resume` |
| Codex | `codex` | `codex exec resume <id>` | `codex exec -C <dir>` without `resume` |

Pick the backend per job: `--backend cursor` (default) or `--backend codex`. Do not mix a Cursor thread id with `--backend codex`, or the reverse.

## Requirements

- Linux with systemd user sessions
- Python 3.9+ (stdlib only)
- Cursor CLI and/or Codex, logged in for non-interactive use
- Optional, once: `sudo loginctl enable-linger $USER` so jobs run while logged out

## Install

```bash
git clone https://github.com/numanzahid/schedule-agent.git
cd schedule-agent
./scripts/install.sh
./scripts/verify.sh
schedule-agent validate
```

Install copies:

- CLI to `~/.local/bin/schedule-agent`
- Python package to `~/.local/lib/schedule-agent/`
- skill to `~/.cursor/skills/schedule-agent/` and `~/.codex/skills/schedule-agent/`
- two systemd user units, then enables the timer

`~/.local/bin` must be on `PATH`. Open a new agent turn after install so the skill is loaded.

## Quick start

Resume an existing chat:

```bash
schedule-agent chats --backend cursor --cwd "$PWD"
schedule-agent add \
  --backend cursor \
  --chat-id <thread-id> \
  --name daily-report \
  --cron "0 6 * * *" \
  --prompt "Run the report and post markdown. Do not ask questions; complete autonomously."
```

Start a new chat in a folder (first run creates it, later runs resume it):

```bash
schedule-agent add \
  --backend cursor \
  --new \
  --workspace "$PWD" \
  --name nightly \
  --cron "0 2 * * *" \
  --prompt "Run tests and summarize. Do not ask questions; complete autonomously."
```

Codex, one-shot, extra flags:

```bash
schedule-agent add \
  --backend codex \
  --new \
  --workspace "$PWD" \
  --name remind \
  --at "now + 2 hours" \
  --prompt "Check the pending task. Do not ask questions; complete autonomously." \
  --arg -s --arg workspace-write
```

```bash
schedule-agent list
schedule-agent run nightly
schedule-agent log nightly
schedule-agent remove nightly
```

## Commands

| Command | Purpose |
|---------|---------|
| `add` | Create a job |
| `list` / `show` / `remove` | Inspect and delete |
| `enable` / `disable` | Toggle without deleting |
| `run <name>` | Run now (ignore the clock) |
| `tick` | Run due jobs (systemd calls this) |
| `chats` | List local chats (`--backend cursor\|codex\|all`) |
| `validate` | Check CLIs + timer |
| `log <name>` | Print the job log |
| `setup` | Write/enable the two user units |

`list`, `show`, `remove`, `chats`, and `validate` accept `--json`.

### `add` flags

Exactly one of `--chat-id` or `--new`. Exactly one of `--cron` or `--at`. Exactly one of `--prompt` or `--prompt-file`.

| Flag | Meaning |
|------|---------|
| `--backend` | `cursor` (default) or `codex` |
| `--chat-id` | Resume this thread |
| `--new` | Create a chat in `--workspace` on first run, then resume it |
| `--new-each-run` | Create a fresh chat every run (implies `--new`) |
| `--workspace` | Project folder (required with `--new`; optional for Cursor resume if the chat metadata has `cwd`) |
| `--prompt` | Text posted into the chat |
| `--prompt-file` | Read the prompt from a file |
| `--name` | Stable job id (otherwise generated) |
| `--cron` | 5 fields: `minute hour dom month dow` |
| `--at` | `now + 2 hours` or ISO-8601. Prefer `run` for "right now"; `--at now` can race the minutely timer |
| `--timeout` | Kill the process after this (default `30m`; also `30s`, `2h`, `1d`) |
| `--model` | Passed to Cursor `--model` or Codex `-m` |
| `--arg` | Extra backend flag or value (repeatable) |
| `--args` | Extra backend flags as one shell-quoted string |
| `--replace` | Overwrite the same `--name` |
| `--dry-run` | Print the backend command; do not save |
| `--json` | Print the saved job as JSON |

If a flag starts with `-`, use `--args '--sandbox disabled'` or `--arg=--sandbox` so the parser does not treat it as a `schedule-agent` option.

## How a run works

Jobs: `~/.config/schedule-agent/jobs.json`

Timer (only these two files):

- `~/.config/systemd/user/cursor-schedule.timer` (minutely, `Persistent=true`)
- `~/.config/systemd/user/cursor-schedule.service` (`schedule-agent tick`)

Each due job:

1. Takes a per-job flock (the same job overlapping prints `SKIP` and does not mark success; other jobs still run)
2. Runs Cursor CLI or Codex with stdin closed
3. Appends `~/.local/state/schedule-agent/logs/<name>.log` with start time, chat id, command, output, end time, exit code
4. Stores `lastRun` / `lastStatus` / `lastExit`
5. If the job was `--new`, captures the created Cursor `session_id` or Codex `thread_id` and writes `chatId` so the next tick resumes (unless `--new-each-run`)
6. One-shot `--at` jobs disable after the first attempt

The turn is finished when the CLI process exits. That is also how the scheduler knows it is safe to treat the run as closed. Exit `0` is success. Exit `124` means `--timeout` killed it (a hang and a job that needed more time look the same unless you raise `--timeout`). Exit `4` is `SKIP` (already running).

Cron jobs that were missed after a previous run can catch up within 24 hours. A brand-new cron job waits for the next matching minute.

Optional binary overrides: `SCHEDULE_AGENT_BIN` (Cursor `agent`) and `SCHEDULE_CODEX_BIN`.

## Skills (how agents use this themselves)

Agents do not learn the flags from training data. Install copies `skill/SKILL.md` to:

| Product | Path |
|---------|------|
| Cursor | `~/.cursor/skills/schedule-agent/SKILL.md` |
| Codex | `~/.codex/skills/schedule-agent/SKILL.md` |

The skill `description` is what gets it selected when someone asks to schedule, remind, cron, or spawn a later agent run. The body tells the agent to call `schedule-agent`, pick `--backend`, resolve `--chat-id` or use `--new --workspace`, and confirm with `show` / `remove`.

Optional project hint in `AGENTS.md`:

```text
Scheduled follow-ups: use `schedule-agent` (skill: schedule-agent).
```

## Cursor CLI

Unattended runs always use `--print --force --trust`. Resume vs spawn:

```bash
# resume
agent --workspace=<dir> --resume=<id> -p "<prompt>" --print --output-format text --force --trust

# spawn (--new)
agent --workspace=<dir> -p "<prompt>" --print --output-format json --force --trust
```

Spawn uses JSON so the new `session_id` can be stored.

Project `.cursor/cli.json` may contain **only** `permissions` (the CLI rejects `approvalMode` there):

```json
{
  "permissions": {
    "allow": ["Shell(*)", "Read(**)", "Write(**)"],
    "deny": ["Shell(git push)", "Read(.env*)"]
  }
}
```

See `examples/cli.json`. Keep `approvalMode` in `~/.cursor/cli-config.json` if needed.

`schedule-agent chats --backend cursor` reads `~/.cursor/chats`. `--workspace` is optional when that metadata has `cwd`.

## Codex

Unattended runs use `codex exec` (not interactive `codex resume`). Resume vs spawn:

```bash
# resume
codex exec -C <workspace> \
  --skip-git-repo-check --color never \
  --dangerously-bypass-approvals-and-sandbox \
  -o <log-dir>/<name>.last.txt \
  resume <session-id> "<prompt>"

# spawn (--new)
codex exec -C <workspace> \
  --skip-git-repo-check --color never \
  --dangerously-bypass-approvals-and-sandbox \
  --json \
  -o <log-dir>/<name>.last.txt \
  "<prompt>"
```

Spawn adds `--json` so the new `thread_id` can be stored. Confirm `codex login status` before relying on a schedule.

`schedule-agent chats --backend codex` reads `~/.codex/sessions`. Pass `--workspace` if a session has no recorded cwd.

## Uninstall

```bash
./scripts/uninstall.sh           # keep jobs/logs
./scripts/uninstall.sh --purge   # also delete jobs/logs
```

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Job never runs | `schedule-agent validate`; `systemctl --user status cursor-schedule.timer` |
| No chat message | `schedule-agent log <name>` |
| `SKIP: already running` | Previous run still holds the lock, or `--at now` raced the minutely tick; use `schedule-agent run <name>` |
| Exit 124 | Increase `--timeout` or inspect the log for a hang |
| Permission prompts (Cursor) | Expand `.cursor/cli.json` allow rules |
| Invalid project config (Cursor) | `.cursor/cli.json` must be permissions-only JSON |
| Codex auth errors | `codex login status` then `codex login` |
| Logged-out jobs missing | `loginctl show-user $USER -p Linger` |
| Chat id unknown | `schedule-agent chats --backend cursor\|codex --cwd "$PWD"` |
| Skill not used | New agent turn after install; check the skill paths above |

## Layout

| Path | Role |
|------|------|
| `bin/schedule-agent` | Launcher on `PATH` |
| `schedule_agent/` | CLI, Cursor/Codex backends, jobs, tick |
| `skill/SKILL.md` | Source skill copied to Cursor and Codex |
| `scripts/install.sh` | Install CLI, both skills, enable the timer |
| `scripts/uninstall.sh` | Remove CLI, skills, units (`--purge` also drops jobs/logs) |
| `tests/` | Unit tests |
| `examples/cli.json` | Sample Cursor permissions-only config |

## License

MIT
