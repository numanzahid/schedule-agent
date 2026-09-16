from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from schedule_agent.backends import normalize_backend

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
    return rows if target else iter_chats(backend)


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
    hint = "~/.codex/sessions" if kind == "codex" else "~/.cursor/chats"
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
