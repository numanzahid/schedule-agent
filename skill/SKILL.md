---
name: schedule-agent
description: >-
  Schedules prompts into an existing agent chat after the interactive session
  is closed. Use when the user wants a reminder, cron, one-shot, or recurring
  agent run in a chat thread; when they mention schedule-agent, Cursor CLI,
  at/cron jobs, or systemd user timers for agents.
---

# schedule-agent

Use the `schedule-agent` CLI. Do not write per-job files under `~/.config/systemd/user/`. Do not use a `sleep` loop in an IDE terminal (it dies when the chat closes).

Supported now: **Cursor CLI** (`agent`). Codex is planned.

## Workflow

1. `schedule-agent validate` (and `validate --chat-id <id>` when the id is known).
2. Resolve chat id: user-supplied, or `schedule-agent chats --cwd "$PWD" --json`.
3. Compose a prompt that names exact steps and ends with: `Do not ask questions; complete autonomously.`
4. Add the job (`--at` or `--cron`, never both).
5. Confirm with `schedule-agent show <name>` and tell the user how to cancel: `schedule-agent remove <name>`.

If validate says the timer is off: `schedule-agent setup`.

## Commands

```bash
schedule-agent add --chat-id <uuid> --prompt "..." --at "now + 2 hours" --name reminder
schedule-agent add --chat-id <uuid> --prompt "..." --cron "0 6 * * *" --name daily-report
schedule-agent add --chat-id <uuid> --prompt-file /tmp/prompt.txt --cron "0 9 * * 1" --name monday
schedule-agent list --json
schedule-agent show <name>
schedule-agent remove <name>
schedule-agent run <name>
schedule-agent log <name>
schedule-agent chats --cwd "$PWD" --json
schedule-agent validate --chat-id <uuid>
```

`--workspace` is optional for Cursor CLI when `~/.cursor/chats/*/<id>/meta.json` has `cwd`.

## Schedule mapping

| User says | Flag |
|-----------|------|
| in 2 hours / at 21:00 today | `--at "now + 2 hours"` or `--at "2026-09-16T21:00:00"` |
| every day at 6am | `--cron "0 6 * * *"` |
| every Monday 9am | `--cron "0 9 * * 1"` |
| every 15 minutes | `--cron "*/15 * * * *"` |

Cron is 5 fields: minute hour dom month dow. One dispatcher timer wakes once a minute; `tick` runs matching jobs.

## Prompt rules

- Name any scripts to run, files to touch, and the markdown to post in chat.
- End with: `Do not ask questions; complete autonomously.`
- For cleanup: `If nothing to do, reply exactly: NO_ACTION`
- Do not expand scope. Do not git commit unless the prompt says to.

## Cursor CLI config

Unattended Cursor CLI runs use `--force` and `--trust`. Project `.cursor/cli.json` may contain **only** `permissions`:

```json
{
  "permissions": {
    "allow": ["Shell(*)", "Read(**)", "Write(**)"],
    "deny": ["Shell(git push)"]
  }
}
```

Keep `approvalMode` in `~/.cursor/cli-config.json` if needed.

## Do not

- `crontab -e`, `sudo crontab`, or files in `/etc/cron.d`
- New systemd units per job
- Call the agent CLI by hand unless debugging (`schedule-agent run` is the path)
- Ask the user questions after they asked to schedule; pick `--name` from the task slug
