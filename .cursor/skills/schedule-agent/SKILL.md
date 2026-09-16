---
name: schedule-agent
description: >-
  Schedules prompts into an existing or new Cursor CLI or Codex chat after the
  interactive session is closed. Use when the user wants a reminder, cron,
  one-shot, new chat in a folder, or recurring agent run; when they mention
  schedule-agent, --new, --resume, at/cron, or systemd timers for agents.
---

# schedule-agent

Use the `schedule-agent` CLI. Do not write per-job files under `~/.config/systemd/user/`. Do not use a `sleep` loop in an IDE terminal (it dies when the chat closes).

Supported backends: **Cursor CLI** (`agent`, default) and **Codex** (`codex exec`). Resume an existing chat with `--chat-id`, or start one with `--new --workspace <dir>`.

## Workflow

1. `schedule-agent validate --backend cursor` or `--backend codex`.
2. Resolve chat id: user-supplied, or `schedule-agent chats --backend <cursor|codex> --cwd "$PWD" --json`.
3. Compose a prompt that names exact steps and ends with: `Do not ask questions; complete autonomously.`
4. Add the job with `--backend cursor` or `--backend codex` (`--at` or `--cron`, never both).
5. Confirm with `schedule-agent show <name>` and tell the user how to cancel: `schedule-agent remove <name>`.

If validate says the timer is off: `schedule-agent setup`.

## Which backend and chat id

Match the agent that should wake up, not necessarily the agent writing the job.

| Goal | `--backend` | `--chat-id` |
|------|-------------|-------------|
| Continue **this** Cursor chat later | `cursor` | `schedule-agent chats --backend cursor --cwd "$PWD" --json` |
| Continue **this** Codex chat later | `codex` | `schedule-agent chats --backend codex --cwd "$PWD" --json` |
| Start a **new** chat | matching backend | `--new --workspace /abs/path` (no `--chat-id`) |
| Wake a **different** existing chat | that chat's backend | that chat's id |

`--new` creates a chat on the first run in `--workspace`, then later ticks resume it. `--new-each-run` starts a fresh chat every time. Pass extra CLI flags with `--arg` (repeatable) or `--args '...'`.

## Commands

```bash
schedule-agent add --backend cursor --chat-id <uuid> --prompt "..." --at "now + 2 hours" --name reminder
schedule-agent add --backend cursor --new --workspace /path/to/project --prompt "..." --at "now + 10 minutes" --name fresh
schedule-agent add --backend cursor --new --new-each-run --workspace /path/to/project --cron "0 6 * * *" --name daily-fresh
schedule-agent add --backend cursor --new --workspace "$PWD" --at "now" --prompt "..." --args "--sandbox disabled"
schedule-agent add --backend codex --chat-id <uuid> --workspace "$PWD" --prompt "..." --cron "0 6 * * *" --name daily
schedule-agent add --backend codex --new --workspace "$PWD" --prompt "..." --at "now + 1 hour" --arg -s --arg workspace-write
schedule-agent list --json
schedule-agent show <name>
schedule-agent remove <name>
schedule-agent run <name>
schedule-agent log <name>
schedule-agent chats --backend all --cwd "$PWD" --json
schedule-agent validate --backend codex --chat-id <uuid>
```

For Cursor CLI, `--workspace` is optional when `~/.cursor/chats/*/<id>/meta.json` has `cwd`. For Codex, pass `--workspace` if `chats` does not show a cwd.

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

## Codex notes

Unattended Codex uses `codex exec` (resume or spawn) with `--dangerously-bypass-approvals-and-sandbox`. Confirm `codex login status` first. Do not use interactive `codex resume` for schedules.

## Do not

- `crontab -e`, `sudo crontab`, or files in `/etc/cron.d`
- New systemd units per job
- Call the agent CLI by hand unless debugging (`schedule-agent run` is the path)
- Ask the user questions after they asked to schedule; pick `--name` from the task slug
- Mix Cursor and Codex ids on the same job
