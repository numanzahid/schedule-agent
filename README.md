# schedule-agent

Schedule a prompt into an existing agent chat after the interactive session is closed.

A `sleep` loop inside an IDE terminal dies when that session ends. This tool stores jobs in a JSON registry and uses **one** systemd user timer (once a minute) to resume the same chat.

```text
systemd user timer (2 files, forever)
  -> schedule-agent tick
  -> Cursor CLI or Codex resume
  -> new messages in the same chat thread
```

## Supported agents

| Agent | Status | CLI | Resume command |
|-------|--------|-----|----------------|
| Cursor CLI | supported | `agent` | `agent --resume <id> -p "..." --print --force --trust` |
| Codex | supported | `codex` | `codex exec resume <id> "..."` |

Pick the backend per job with `--backend cursor` (default) or `--backend codex`.

## Requirements

- Linux with systemd user sessions
- Python 3.9+ (no extra pip packages)
- At least one supported agent CLI, logged in for non-interactive use
- Optional once: `sudo loginctl enable-linger $USER` so jobs run while logged out

## Install

```bash
git clone https://github.com/numanzahid/schedule-agent.git
cd schedule-agent
./scripts/install.sh
./scripts/verify.sh
```

This copies the CLI to `~/.local/bin/schedule-agent`, installs the skill for both Cursor and Codex, and enables the dispatcher timer.

`~/.local/bin` must be on your PATH.

## How agents learn this tool

They do not get the CLI flags from training data. After install, the same `skill/SKILL.md` is copied to:

- Cursor: `~/.cursor/skills/schedule-agent/SKILL.md`
- Codex: `~/.codex/skills/schedule-agent/SKILL.md`

The YAML `description` is what makes the skill show up when the user asks to schedule, remind, cron, or resume a chat later. The skill body tells the agent to run `schedule-agent`, pick `--backend cursor` or `--backend codex`, and resolve `--chat-id` with `schedule-agent chats`.

A new Cursor or Codex turn is needed after the first install so the skill is picked up.

You can also point an agent at the repo README, or add a line to a project `AGENTS.md`:

```text
Scheduled follow-ups: use `schedule-agent` (skill: schedule-agent).
```

## Quick start

```bash
schedule-agent validate
schedule-agent chats --backend cursor --cwd "$PWD"
schedule-agent chats --backend codex --cwd "$PWD"

# Cursor CLI
schedule-agent add \
  --backend cursor \
  --chat-id <cursor-thread-id> \
  --name daily-report \
  --cron "0 6 * * *" \
  --prompt "Run the report script and post markdown. Do not ask questions; complete autonomously."

# Codex
schedule-agent add \
  --backend codex \
  --chat-id <codex-session-id> \
  --workspace "$PWD" \
  --name reminder \
  --at "now + 2 hours" \
  --prompt "Check the pending task. Do not ask questions; complete autonomously."

schedule-agent list
schedule-agent run daily-report
schedule-agent log reminder
schedule-agent remove daily-report
```

## Commands

| Command | Purpose |
|---------|---------|
| `add` | Create a job (`--cron` or `--at`) |
| `list` / `show` / `remove` | Inspect and delete |
| `enable` / `disable` | Toggle without deleting |
| `run` | Run now (ignore the clock) |
| `tick` | Run due jobs (systemd calls this) |
| `chats` | List local chats (`--backend cursor\|codex\|all`) |
| `validate` | Preflight CLIs + timer (`--backend` selects which CLI is required) |
| `log` | Tail a job log |
| `setup` | Write/enable the two user units |

`add` flags: `--backend`, `--chat-id` or `--new`, `--workspace`, `--prompt` or `--prompt-file`, `--cron` or `--at`, optional `--name`, `--timeout` (default `30m`), `--model`, `--arg` / `--args`, `--new-each-run`, `--replace`, `--json`, `--dry-run`.

`--new` starts a new chat in `--workspace` (required). The first run creates the session and stores its id; later runs resume it unless you also pass `--new-each-run`.

`--arg` is repeatable extra CLI tokens for that backend. `--args` is the same thing as one shell-quoted string. If a flag starts with `-`, prefer `--args '--sandbox disabled'` or `--arg=--sandbox` so the shell/parser does not eat it.

```bash
schedule-agent add --backend cursor --new --workspace "$PWD" \
  --name nightly --cron "0 2 * * *" \
  --prompt "Run tests and summarize. Do not ask questions; complete autonomously." \
  --args "--sandbox disabled"

schedule-agent add --backend codex --new --workspace "$PWD" \
  --name fresh-codex --at "now + 5 minutes" \
  --prompt "Reply with exactly: HI. Do not ask questions; complete autonomously." \
  --arg -s --arg workspace-write
```

`--at` examples: `now + 2 hours`, `2026-09-17T06:00:00`. `--cron` is 5 fields (`0 6 * * *`).

## How scheduling works

Jobs live in `~/.config/schedule-agent/jobs.json`.

systemd gets **two** unit files only:

- `~/.config/systemd/user/cursor-schedule.service`
- `~/.config/systemd/user/cursor-schedule.timer`

Adding a job never creates more units. The timer fires every minute; `tick` runs jobs whose cron matches (with a 24h catch-up after a previous run) or whose `--at` time has passed.

One-shot jobs disable themselves after the first attempt so a failure does not retry every minute. Re-enable or `run` to retry.

Per-job flock prevents overlap. Logs: `~/.local/state/schedule-agent/logs/<name>.log`.

A run is done when the agent CLI process exits. Default timeout is 30 minutes (`--timeout` to change). Exit `124` means the timeout killed the process.

## Cursor CLI notes

Unattended Cursor CLI runs use `--print --force --trust`. Project `.cursor/cli.json` may contain **only** `permissions` (the CLI rejects `approvalMode` there):

```json
{
  "permissions": {
    "allow": ["Shell(*)", "Read(**)", "Write(**)"],
    "deny": ["Shell(git push)", "Read(.env*)"]
  }
}
```

See `examples/cli.json`. After install, Cursor loads `~/.cursor/skills/schedule-agent/SKILL.md`.

## Codex notes

Unattended Codex runs use:

```bash
codex exec resume <session-id> "<prompt>" \
  -C <workspace> \
  --skip-git-repo-check \
  --color never \
  --dangerously-bypass-approvals-and-sandbox
```

That skips approval prompts so a scheduled job cannot hang waiting for a TUI. Keep `--timeout` set. Confirm login with `codex login status` before relying on a schedule.

`schedule-agent chats --backend codex` reads session files under `~/.codex/sessions`. `--workspace` is required if a session has no recorded cwd.

Do not use interactive `codex resume` for scheduled jobs. After install, Codex loads `~/.codex/skills/schedule-agent/SKILL.md`.

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
| Permission prompts (Cursor CLI) | expand `.cursor/cli.json` allow rules |
| Invalid project config (Cursor CLI) | `.cursor/cli.json` must be permissions-only JSON |
| Codex auth errors | `codex login status` then `codex login` |
| Logged-out jobs missing | `loginctl show-user $USER -p Linger` then `sudo loginctl enable-linger $USER` |
| Chat id unknown | `schedule-agent chats --backend cursor\|codex --cwd "$PWD"` |

## License

MIT
