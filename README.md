# schedule-agent

Schedule a coding-agent prompt for later. The job still runs after you close the IDE chat.

Use it to:

- resume an **existing** Cursor CLI or Codex thread
- start a **new** thread in a chosen folder
- run once (`--at`) or on a cron (`--cron`)
- pass extra flags through to `agent` or `codex`

A `sleep` loop inside an IDE terminal dies when that session ends. This tool stores jobs in JSON and uses **one** systemd user timer (once a minute). Adding jobs does not create more systemd units.

```text
systemd user timer  (2 files, forever)
  -> schedule-agent tick
  -> Cursor CLI or Codex
       resume existing chat  OR  start a new one in --workspace
  -> process exits when the turn is done
  -> log + lastStatus
```

## Supported agents

| Agent | CLI | Existing chat | New chat |
|-------|-----|---------------|----------|
| Cursor CLI | `agent` | `agent --resume <id> -p "..."` | `agent --workspace=... -p "..."` |
| Codex | `codex` | `codex exec resume <id> "..."` | `codex exec -C <dir> "..."` |

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

Exactly one of `--chat-id` or `--new`. Exactly one of `--cron` or `--at`. `--prompt` or `--prompt-file`.

| Flag | Meaning |
|------|---------|
| `--backend` | `cursor` (default) or `codex` |
| `--chat-id` | Resume this thread |
| `--new` | Create a chat in `--workspace` on first run, then resume it |
| `--new-each-run` | Create a fresh chat every run |
| `--workspace` | Project folder (required with `--new`) |
| `--name` | Stable job id (otherwise generated) |
| `--cron` | 5 fields: `minute hour dom month dow` |
| `--at` | `now + 2 hours` or ISO-8601 |
| `--timeout` | Kill the process after this (default `30m`; also `30s`, `2h`, `1d`) |
| `--model` | Passed to Cursor `--model` or Codex `-m` |
| `--arg` | Extra backend flag or value (repeatable) |
| `--args` | Extra backend flags as one shell-quoted string |
| `--replace` | Overwrite the same `--name` |
| `--dry-run` | Print the backend command; do not save |

If a flag starts with `-`, use `--args '--sandbox disabled'` or `--arg=--sandbox` so the parser does not treat it as a `schedule-agent` option.

`--new-each-run` implies `--new`.

## How a run works

Jobs: `~/.config/schedule-agent/jobs.json`

Timer (only these two files):

- `~/.config/systemd/user/cursor-schedule.timer` (minutely, `Persistent=true`)
- `~/.config/systemd/user/cursor-schedule.service` (`schedule-agent tick`)

Each due job:

1. Takes a per-job flock (overlap prints `SKIP` and does not mark success)
2. Runs Cursor CLI or Codex with stdin closed
3. Appends `~/ .local/state/schedule-agent/logs/<name>.log` with start time, chat id, command, output, end time, exit code
4. Stores `lastRun` / `lastStatus` / `lastExit`
5. If the job was `--new`, writes the created `chatId` so the next tick resumes (unless `--new-each-run`)
6. One-shot `--at` jobs disable after the first attempt

The turn is finished when the CLI process exits. That is also how the scheduler knows it is safe to treat the run as closed. Exit `0` is success. Exit `124` means `--timeout` killed it (a hang and a job that needed more time look the same unless you raise `--timeout`).

Cron jobs that were missed after a previous run can catch up within 24 hours. A brand-new cron job waits for the next matching minute.

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

Unattended runs use `--print --force --trust`. For `--new`, output is JSON so the new `session_id` can be stored.

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

Unattended runs use `codex exec` (not interactive `codex resume`):

```bash
codex exec resume <session-id> "<prompt>" \
  -C <workspace> \
  --skip-git-repo-check \
  --color never \
  --dangerously-bypass-approvals-and-sandbox
```

`--new` omits `resume` and adds `--json` so the new `thread_id` can be stored. Confirm `codex login status` before relying on a schedule.

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
| `SKIP: already running` | Previous run still holds the lock |
| Exit 124 | Increase `--timeout` or inspect the log for a hang |
| Permission prompts (Cursor) | Expand `.cursor/cli.json` allow rules |
| Invalid project config (Cursor) | `.cursor/cli.json` must be permissions-only JSON |
| Codex auth errors | `codex login status` then `codex login` |
| Logged-out jobs missing | `loginctl show-user $USER -p Linger` |
| Chat id unknown | `schedule-agent chats --backend cursor\|codex --cwd "$PWD"` |
| Skill not used | New agent turn after install; check the skill paths above |

## License

MIT
