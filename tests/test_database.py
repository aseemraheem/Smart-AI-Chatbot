import sqlite3

import pytest

from app.database import queries
from app.database.db import get_db


@pytest.fixture
def db(app):
    with app.app_context():
        yield get_db()


def test_schema_creates_tables(db):
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"conversations", "messages", "settings"} <= names


def test_messages_come_back_in_insertion_order(db):
    conv = queries.create_conversation(db)
    for i in range(5):
        queries.add_message(db, conv["id"], "user" if i % 2 == 0 else "assistant", f"m{i}")
    assert [m["content"] for m in queries.get_messages(db, conv["id"])] == [f"m{i}" for i in range(5)]
    assert [m["content"] for m in queries.get_recent_messages(db, conv["id"], 2)] == ["m3", "m4"]


def test_invalid_role_is_rejected(db):
    conv = queries.create_conversation(db)
    with pytest.raises(ValueError):
        queries.add_message(db, conv["id"], "system", "nope")


def test_database_also_enforces_roles(db):
    conv = queries.create_conversation(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'admin', 'x', 'now')", (conv["id"],))


def test_deleting_a_conversation_cascades_to_messages(db):
    conv = queries.create_conversation(db)
    queries.add_message(db, conv["id"], "user", "hi")
    assert queries.delete_conversation(db, conv["id"]) is True
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert queries.delete_conversation(db, conv["id"]) is False


def test_adding_a_message_updates_last_updated(db):
    conv = queries.create_conversation(db)
    queries.add_message(db, conv["id"], "user", "hi")
    assert queries.get_conversation(db, conv["id"])["updated_at"] >= conv["updated_at"]


def test_sql_injection_text_is_just_text(db):
    queries.create_conversation(db, "x'; DROP TABLE messages; --")
    assert queries.list_conversations(db, "'; DROP")  # found as ordinary text
    assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='messages'").fetchone()[0] == 1


@pytest.mark.parametrize("text,expected", [
    ("Hello world", "Hello world"),
    ("\n\n  Spaced    out  \nsecond line", "Spaced out"),
    ("", "New chat"),
    ("a" * 100, "a" * 47 + "…"),
])
def test_make_title(text, expected):
    assert queries.make_title(text) == expected


def test_settings_defaults_and_validation(db):
    assert queries.get_settings(db) == {"theme": "dark", "response_style": "balanced"}
    queries.set_setting(db, "theme", "light")
    assert queries.get_settings(db)["theme"] == "light"
    with pytest.raises(ValueError):
        queries.set_setting(db, "theme", "pink")
