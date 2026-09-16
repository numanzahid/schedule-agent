# schedule-agent

Schedule a prompt into an existing agent chat after the interactive session is closed.

A `sleep` loop inside an IDE terminal dies when that session ends. This tool stores jobs in a JSON registry and uses **one** systemd user timer (once a minute) to resume the same chat.

```text
systemd user timer (2 files, forever)
  -> schedule-agent tick
  -> <agent-cli> --resume=<chat-id> -p "..."
  -> new messages in the same chat thread
```

## Supported agents

| Agent | Status | CLI |
|-------|--------|-----|
| Cursor CLI | supported | `agent` (`~/.local/bin/agent`) |
| Codex | planned | |

The job model (chat id, prompt, `--at` / `--cron`, timeout, logs) is shared. Only the resume command differs per backend.

## Requirements

- Linux with systemd user sessions
- Python 3.9+ (no extra pip packages)
- A supported agent CLI, logged in for non-interactive use
- Optional once: `sudo loginctl enable-linger $USER` so jobs run while logged out

## Install

```bash
git clone https://github.com/numanzahid/schedule-agent.git
cd schedule-agent
./scripts/install.sh
./scripts/verify.sh
```

This copies the CLI to `~/.local/bin/schedule-agent`, installs the skill, and enables the dispatcher timer.

`~/.local/bin` must be on your PATH.

## Quick start

```bash
schedule-agent validate
schedule-agent chats --cwd "$PWD"

schedule-agent add \
  --chat-id <chat-id> \
  --name daily-report \
  --cron "0 6 * * *" \
  --prompt "Run the report script and post markdown. Do not ask questions; complete autonomously."

schedule-agent add \
  --chat-id <chat-id> \
  --name reminder \
  --at "now + 2 hours" \
  --prompt "Check the pending task. Do not ask questions; complete autonomously."

schedule-agent list
schedule-agent run daily-report
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
| `chats` | List local chat ids (Cursor CLI backend) |
| `validate` | Preflight agent CLI + timer |
| `log` | Tail a job log |
| `setup` | Write/enable the two user units |

`add` flags: `--chat-id`, `--prompt` or `--prompt-file`, `--cron` or `--at`, optional `--name`, `--workspace`, `--timeout` (default `30m`), `--model`, `--replace`, `--json`, `--dry-run`.

`--at` examples: `now + 2 hours`, `2026-09-17T06:00:00`. `--cron` is 5 fields (`0 6 * * *`).

## How scheduling works

Jobs live in `~/.config/schedule-agent/jobs.json`.

systemd gets **two** unit files only:

- `~/.config/systemd/user/cursor-schedule.service`
- `~/.config/systemd/user/cursor-schedule.timer`

Adding a job never creates more units. The timer fires every minute; `tick` runs jobs whose cron matches (with a 24h catch-up after a previous run) or whose `--at` time has passed.

One-shot jobs disable themselves after the first attempt so a failure does not retry every minute. Re-enable or `run` to retry.

Per-job flock prevents overlap. Logs: `~/.local/state/schedule-agent/logs/<name>.log`.

A run is done when the agent CLI process exits (`--print` / non-interactive mode). Default timeout is 30 minutes (`--timeout` to change). Exit `124` means the timeout killed the process.

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

See `examples/cli.json`. After install, Cursor can load `~/.cursor/skills/schedule-agent/SKILL.md`.

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
| Logged-out jobs missing | `loginctl show-user $USER -p Linger` then `sudo loginctl enable-linger $USER` |
| Chat id unknown | `schedule-agent chats --cwd "$PWD"` |

## License

MIT
