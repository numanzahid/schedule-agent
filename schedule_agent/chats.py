from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from schedule_agent.backends import normalize_backend
from schedule_agent.config import claude_config_dir

CHATS_ROOT = Path.home() / ".cursor" / "chats"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"


class ChatError(Exception):
    pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        return data
    return None


def iter_chats(backend: str | None = None) -> list[dict[str, Any]]:
    kind = normalize_backend(backend)
    if kind == "codex":
        return iter_codex_chats()
    if kind == "claude":
        return iter_claude_chats()
    return iter_cursor_chats()


def iter_cursor_chats() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not CHATS_ROOT.exists():
        return rows
    for meta_path in CHATS_ROOT.glob("*/*/meta.json"):
        chat_id = meta_path.parent.name
        data = _read_json(meta_path) or {}
        if data.get("isSubagent"):
            continue
        mtime = datetime.fromtimestamp(meta_path.stat().st_mtime).astimezone()
        rows.append(
            {
                "id": chat_id,
                "backend": "cursor",
                "title": data.get("title") or "(untitled)",
                "cwd": data.get("cwd"),
                "hash": meta_path.parent.parent.name,
                "updatedAt": mtime.isoformat(timespec="seconds"),
                "metaPath": str(meta_path),
            }
        )
    rows.sort(key=lambda row: row["updatedAt"], reverse=True)
    return rows


def iter_codex_chats() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not CODEX_SESSIONS.exists():
        return rows
    for path in CODEX_SESSIONS.rglob("rollout-*.jsonl"):
        row = _codex_row(path)
        if row:
            rows.append(row)
    rows.sort(key=lambda row: row["updatedAt"], reverse=True)
    return rows


def _codex_row(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
    except OSError:
        return None
    try:
        event = json.loads(first)
    except json.JSONDecodeError:
        return None
    payload = event.get("payload") if isinstance(event, dict) else None
    if not isinstance(payload, dict):
        return None
    chat_id = payload.get("id")
    if not chat_id:
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    title = payload.get("source") or payload.get("originator") or "(untitled)"
    return {
        "id": str(chat_id),
        "backend": "codex",
        "title": str(title),
        "cwd": payload.get("cwd"),
        "updatedAt": mtime.isoformat(timespec="seconds"),
        "metaPath": str(path),
    }


def iter_claude_chats() -> list[dict[str, Any]]:
    # Only top-level project transcripts: nested subagents are not resumable chats.
    projects = claude_config_dir() / "projects"
    rows: dict[str, dict[str, Any]] = {}
    for project in projects.glob("*"):
        index = _read_json(project / "sessions-index.json") or {}
        entries = index.get("entries")
        metadata = {
            entry["sessionId"]: entry for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("sessionId"), str)
        } if isinstance(entries, list) else {}
        for path in project.glob("*.jsonl"):
            row = _claude_row(path, metadata.get(path.stem) or {})
            if row and (row["id"] not in rows or row["updatedAt"] > rows[row["id"]]["updatedAt"]):
                rows[row["id"]] = row
    return sorted(rows.values(), key=lambda row: row["updatedAt"], reverse=True)


def _claude_row(path: Path, metadata: dict[str, Any]) -> dict[str, Any] | None:
    try:
        UUID(path.stem)
    except ValueError:
        return None
    if metadata.get("isSidechain"):
        return None
    cwd = metadata.get("projectPath") or metadata.get("cwd")
    title = metadata.get("customTitle") or metadata.get("summary") or metadata.get("firstPrompt")
    found = False
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        with path.open(encoding="utf-8", errors="replace") as handle:
            # Session files may be large. Metadata is near the start, after optional
            # queue/snapshot events; never read the full conversation into memory.
            for _ in range(256):
                line = handle.readline(256 * 1024)
                if not line:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("sessionId") != path.stem:
                    continue
                if event.get("isSidechain"):
                    return None
                found = True
                cwd = cwd or event.get("cwd")
                if not title and event.get("type") == "user":
                    message = event.get("message")
                    content = message.get("content") if isinstance(message, dict) else None
                    if isinstance(content, list):
                        content = " ".join(
                            item["text"] for item in content
                            if isinstance(item, dict) and isinstance(item.get("text"), str)
                        )
                    if isinstance(content, str) and content.strip():
                        title = content.strip().splitlines()[0][:120]
                if cwd and title:
                    break
    except OSError:
        return None
    if not found:
        return None
    return {
        "id": path.stem, "backend": "claude", "title": str(title or "(untitled)"),
        "cwd": cwd, "updatedAt": mtime.isoformat(timespec="seconds"), "metaPath": str(path),
    }


def chats_for_cwd(cwd: str | None = None, backend: str | None = None) -> list[dict[str, Any]]:
    target = str(Path(cwd).expanduser().resolve()) if cwd else None
    rows = []
    for row in iter_chats(backend):
        if target and row.get("cwd"):
            try:
                if str(Path(row["cwd"]).expanduser().resolve()) != target:
                    continue
            except OSError:
                continue
        elif target and not row.get("cwd"):
            continue
        rows.append(row)
    return rows


def resolve_workspace(
    chat_id: str,
    override: str | None = None,
    backend: str | None = None,
) -> Path:
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_dir():
            raise ChatError(f"workspace is not a directory: {path}")
        return path

    kind = normalize_backend(backend)
    matches = [row for row in iter_chats(kind) if row["id"] == chat_id]
    hint = {
        "codex": "~/.codex/sessions", "cursor": "~/.cursor/chats",
        "claude": str(claude_config_dir() / "projects"),
    }[kind]
    if not matches:
        raise ChatError(
            f"chat id not found under {hint}: {chat_id}. Pass --workspace /abs/path"
        )
    for row in matches:
        cwd = row.get("cwd")
        if cwd:
            path = Path(str(cwd)).expanduser()
            if path.is_dir():
                return path.resolve()
    raise ChatError(
        f"chat {chat_id} has no cwd recorded. Pass --workspace /abs/path"
    )
