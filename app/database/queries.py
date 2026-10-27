"""Conversation, message and settings operations.

Every query is parameterized; user input is never formatted into SQL.
"""
import re
import uuid
from datetime import datetime, timezone

DEFAULT_TITLE = "New chat"
VALID_ROLES = ("user", "assistant")

DEFAULT_SETTINGS = {"theme": "dark", "response_style": "balanced"}
ALLOWED_SETTINGS = {
    "theme": {"dark", "light"},
    "response_style": {"concise", "balanced", "detailed"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_title(text: str, max_chars: int = 48) -> str:
    """Build a short title from the first line of a user message."""
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    title = re.sub(r"\s+", " ", first_line).strip()
    if not title:
        return DEFAULT_TITLE
    return title if len(title) <= max_chars else title[: max_chars - 1].rstrip() + "…"


# --- Conversations ------------------------------------------------------
def create_conversation(db, title: str = DEFAULT_TITLE) -> dict:
    now = _now()
    conv = {"id": uuid.uuid4().hex, "title": title, "created_at": now, "updated_at": now}
    db.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv["id"], conv["title"], now, now),
    )
    db.commit()
    return conv


def get_conversation(db, conversation_id: str) -> dict | None:
    row = db.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    return dict(row) if row else None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_conversations(db, search: str | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT id, title, created_at, updated_at FROM conversations"
    params: list = []
    if search:
        pattern = f"%{_escape_like(search)}%"
        sql += (
            " WHERE title LIKE ? ESCAPE '\\' OR EXISTS ("
            "SELECT 1 FROM messages m WHERE m.conversation_id = conversations.id "
            "AND m.content LIKE ? ESCAPE '\\')"
        )
        params += [pattern, pattern]
    sql += " ORDER BY updated_at DESC, rowid DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def rename_conversation(db, conversation_id: str, title: str) -> bool:
    cur = db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
    db.commit()
    return cur.rowcount > 0


def delete_conversation(db, conversation_id: str) -> bool:
    cur = db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    db.commit()
    return cur.rowcount > 0


# --- Messages -----------------------------------------------------------
def add_message(db, conversation_id: str, role: str, content: str) -> dict:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid message role: {role!r}")
    now = _now()
    cur = db.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, now),
    )
    db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
    db.commit()
    return {"id": cur.lastrowid, "role": role, "content": content, "created_at": now}


def get_messages(db, conversation_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_messages(db, conversation_id: str, limit: int) -> list[dict]:
    """The last `limit` messages, oldest first."""
    rows = db.execute(
        "SELECT id, role, content, created_at FROM ("
        " SELECT id, role, content, created_at FROM messages"
        " WHERE conversation_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
        (conversation_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_message(db, message_id: int) -> None:
    db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    db.commit()


# --- Settings -----------------------------------------------------------
def get_settings(db) -> dict:
    settings = dict(DEFAULT_SETTINGS)
    for row in db.execute("SELECT key, value FROM settings").fetchall():
        if row["key"] in ALLOWED_SETTINGS and row["value"] in ALLOWED_SETTINGS[row["key"]]:
            settings[row["key"]] = row["value"]
    return settings


def set_setting(db, key: str, value: str) -> None:
    if key not in ALLOWED_SETTINGS or value not in ALLOWED_SETTINGS[key]:
        raise ValueError(f"Unsupported setting: {key}={value!r}")
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()
