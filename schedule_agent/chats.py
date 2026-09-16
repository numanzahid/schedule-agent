from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

CHATS_ROOT = Path.home() / ".cursor" / "chats"


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


def iter_chats() -> list[dict[str, Any]]:
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
                "title": data.get("title") or "(untitled)",
                "cwd": data.get("cwd"),
                "hash": meta_path.parent.parent.name,
                "updatedAt": mtime.isoformat(timespec="seconds"),
                "metaPath": str(meta_path),
            }
        )
    rows.sort(key=lambda row: row["updatedAt"], reverse=True)
    return rows


def chats_for_cwd(cwd: str | None = None) -> list[dict[str, Any]]:
    target = str(Path(cwd).expanduser().resolve()) if cwd else None
    rows = []
    for row in iter_chats():
        if target and row.get("cwd"):
            try:
                if str(Path(row["cwd"]).expanduser().resolve()) != target:
                    continue
            except OSError:
                continue
        elif target and not row.get("cwd"):
            continue
        rows.append(row)
    return rows if target else iter_chats()


def resolve_workspace(chat_id: str, override: str | None = None) -> Path:
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_dir():
            raise ChatError(f"workspace is not a directory: {path}")
        return path

    matches = [row for row in iter_chats() if row["id"] == chat_id]
    if not matches:
        raise ChatError(
            f"chat id not found under ~/.cursor/chats: {chat_id}. "
            "Pass --workspace /abs/path"
        )
    for row in matches:
        cwd = row.get("cwd")
        if cwd:
            path = Path(str(cwd)).expanduser()
            if path.is_dir():
                return path.resolve()
    raise ChatError(
        f"chat {chat_id} has no cwd in meta.json. Pass --workspace /abs/path"
    )
