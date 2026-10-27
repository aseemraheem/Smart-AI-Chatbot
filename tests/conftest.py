"""Shared fixtures. The OpenAI API is always mocked: no key or network needed."""
import json

import pytest

from app import create_app
from app.services import ai_service


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "test-secret",
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "test-model",
        "RATE_LIMIT_PER_MINUTE": 1000,
    })


@pytest.fixture
def anon_client(app):
    """A client that has NOT fetched the page, so it has no CSRF token."""
    return app.test_client()


@pytest.fixture
def client(app):
    """A client that loaded the home page and sends the CSRF header like the browser does."""
    c = app.test_client()
    assert c.get("/").status_code == 200
    with c.session_transaction() as sess:
        token = sess["csrf_token"]
    c.environ_base["HTTP_X_CSRF_TOKEN"] = token
    return c


@pytest.fixture
def fake_ai(monkeypatch):
    """Replace the AI call with a canned streamed reply; records the history sent."""
    calls = []

    def fake_stream_reply(history, response_style="balanced"):
        calls.append([dict(m) for m in history])
        return iter(["Hello", " there"])

    monkeypatch.setattr(ai_service, "stream_reply", fake_stream_reply)
    return calls


def parse_events(response):
    return [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]


def new_conversation(client, title=None):
    body = {"title": title} if title else {}
    return client.post("/api/conversations", json=body).get_json()["conversation"]["id"]
