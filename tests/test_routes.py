import pytest

from app.services import ai_service
from app.services.ai_service import AIServiceError
from tests.conftest import new_conversation, parse_events


def chat(client, cid, message="Hi", **extra):
    # buffered=True reads the whole stream, like a browser does
    return client.post("/api/chat", json={"conversation_id": cid, "message": message, **extra}, buffered=True)


# --- Home page, CSRF, request validation ---------------------------------
def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "What can I help you with?" in html
    assert 'name="csrf-token"' in html
    assert "Content-Security-Policy" in response.headers


def test_state_changing_request_without_csrf_token_is_rejected(anon_client):
    response = anon_client.post("/api/conversations", json={})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_invalid_json_is_handled_safely(client, fake_ai):
    cid = new_conversation(client)
    bad = client.post("/api/chat", data="{not json", content_type="application/json")
    assert bad.status_code == 400
    assert bad.get_json()["error"]["code"] == "invalid_json"
    not_object = client.post("/api/chat", json=["a", "list"])
    assert not_object.status_code == 400
    assert fake_ai == []  # the AI was never called


@pytest.mark.parametrize("message", ["", "   ", "\n\t "])
def test_empty_messages_are_rejected_without_calling_ai(client, fake_ai, message):
    cid = new_conversation(client)
    response = chat(client, cid, message)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "empty_message"
    assert fake_ai == []


def test_non_string_message_is_rejected(client, fake_ai):
    cid = new_conversation(client)
    assert chat(client, cid, 123).status_code == 400
    assert fake_ai == []


@pytest.mark.parametrize("role", ["assistant", "system", "admin"])
def test_invalid_message_roles_are_rejected(client, fake_ai, role):
    cid = new_conversation(client)
    response = chat(client, cid, "Hi", role=role)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_role"
    assert fake_ai == []


def test_message_length_limit_is_enforced(client, app, fake_ai):
    cid = new_conversation(client)
    limit = app.config["MAX_MESSAGE_CHARS"]
    assert chat(client, cid, "x" * (limit + 1)).status_code == 400
    assert chat(client, cid, "x" * limit).status_code == 200


def test_oversized_request_body_is_rejected(app, client):
    app.config["MAX_CONTENT_LENGTH"] = 200
    response = client.post("/api/conversations", json={"title": "x" * 500})
    assert response.status_code == 413


def test_malformed_and_unknown_conversation_ids(client, fake_ai):
    assert client.get("/api/conversations/not-a-valid-id").status_code == 400
    assert client.get("/api/conversations/" + "a" * 32).status_code == 404
    assert chat(client, "../../etc/passwd").status_code == 400
    assert chat(client, "a" * 32).status_code == 404
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 400


# --- Conversations -------------------------------------------------------
def test_create_and_retrieve_conversations(client):
    cid = new_conversation(client)
    data = client.get(f"/api/conversations/{cid}").get_json()
    assert data["conversation"]["title"] == "New chat"
    assert data["messages"] == []
    listing = client.get("/api/conversations").get_json()["conversations"]
    assert [c["id"] for c in listing] == [cid]


def test_messages_are_saved_and_loaded_in_order(client, fake_ai):
    cid = new_conversation(client)
    first = parse_events(chat(client, cid, "First question"))
    assert [e["type"] for e in first] == ["delta", "delta", "done"]
    assert first[-1]["message"]["content"] == "Hello there"
    chat(client, cid, "Second question")
    messages = client.get(f"/api/conversations/{cid}").get_json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "First question"), ("assistant", "Hello there"),
        ("user", "Second question"), ("assistant", "Hello there"),
    ]


def test_title_is_generated_from_first_message_only(client, fake_ai):
    cid = new_conversation(client)
    chat(client, cid, "How do I reverse a list in Python?\nPlease be brief")
    chat(client, cid, "Another question")
    title = client.get(f"/api/conversations/{cid}").get_json()["conversation"]["title"]
    assert title == "How do I reverse a list in Python?"


def test_previous_messages_are_sent_to_the_ai(client, fake_ai):
    cid = new_conversation(client)
    chat(client, cid, "One")
    chat(client, cid, "Two")
    assert [m["content"] for m in fake_ai[1]] == ["One", "Hello there", "Two"]


def test_conversation_histories_are_separate(client, fake_ai):
    a, b = new_conversation(client), new_conversation(client)
    chat(client, a, "Only in A")
    assert client.get(f"/api/conversations/{b}").get_json()["messages"] == []


def test_rename_conversation(client):
    cid = new_conversation(client)
    response = client.patch(f"/api/conversations/{cid}", json={"title": "  My   plan "})
    assert response.status_code == 200
    assert response.get_json()["conversation"]["title"] == "My plan"
    assert client.patch(f"/api/conversations/{cid}", json={"title": "   "}).status_code == 400
    assert client.patch(f"/api/conversations/{cid}", json={"title": "x" * 200}).status_code == 400


def test_delete_conversation_removes_it_and_its_messages(client, fake_ai):
    cid = new_conversation(client)
    chat(client, cid, "Hello")
    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert client.get(f"/api/conversations/{cid}").status_code == 404
    assert client.get("/api/conversations").get_json()["conversations"] == []
    assert client.delete(f"/api/conversations/{cid}").status_code == 404


def test_search_matches_titles_and_message_content(client, fake_ai):
    a = new_conversation(client, "Python tips")
    b = new_conversation(client)
    chat(client, b, "Tell me about volcanoes")
    find = lambda q: [c["id"] for c in client.get("/api/conversations", query_string={"q": q}).get_json()["conversations"]]
    assert find("python") == [a]
    assert find("VOLCANO") == [b]
    assert find("nothing-matches") == []
    assert find("%") == []  # wildcard characters are treated literally


# --- AI failures ---------------------------------------------------------
def test_ai_failure_returns_safe_error_and_saves_nothing(client, monkeypatch):
    def failing(history, response_style="balanced"):
        raise AIServiceError("OpenAI rejected the API key.", 502, "auth_failed")

    monkeypatch.setattr(ai_service, "stream_reply", failing)
    cid = new_conversation(client)
    response = chat(client, cid, "Hi")
    assert response.status_code == 502
    assert response.get_json()["error"] == {"message": "OpenAI rejected the API key.", "code": "auth_failed"}
    assert client.get(f"/api/conversations/{cid}").get_json()["messages"] == []


def test_unexpected_exception_does_not_leak_details(client, monkeypatch):
    def broken(history, response_style="balanced"):
        raise RuntimeError("sk-secret-internal-detail")

    monkeypatch.setattr(ai_service, "stream_reply", broken)
    cid = new_conversation(client)
    response = chat(client, cid, "Hi")
    assert response.status_code == 500
    assert "sk-secret" not in response.get_data(as_text=True)


def test_mid_stream_failure_sends_error_event_and_keeps_partial_text(client, monkeypatch):
    def partial(history, response_style="balanced"):
        def gen():
            yield "Partial answer"
            raise AIServiceError("Connection dropped.", 503, "network_error")
        return gen()

    monkeypatch.setattr(ai_service, "stream_reply", partial)
    cid = new_conversation(client)
    events = parse_events(chat(client, cid, "Hi"))
    assert events[-1]["type"] == "error" and events[-1]["message"] == "Connection dropped."
    messages = client.get(f"/api/conversations/{cid}").get_json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "Partial answer"


def test_not_configured_gives_clear_message(app, client):
    app.config["OPENAI_API_KEY"] = ""
    cid = new_conversation(client)
    response = chat(client, cid, "Hi")  # real ai_service, no key
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "not_configured"
    assert ".env" in response.get_json()["error"]["message"]


# --- Regenerate, rate limit, settings -------------------------------------
def test_regenerate_replaces_the_last_reply(client, monkeypatch):
    replies = iter([["First reply"], ["Second reply"]])
    monkeypatch.setattr(ai_service, "stream_reply", lambda h, s="balanced": iter(next(replies)))
    cid = new_conversation(client)
    chat(client, cid, "Question")
    events = parse_events(client.post("/api/chat", json={"conversation_id": cid, "regenerate": True}, buffered=True))
    assert events[-1]["message"]["content"] == "Second reply"
    messages = client.get(f"/api/conversations/{cid}").get_json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [("user", "Question"), ("assistant", "Second reply")]


def test_regenerate_with_nothing_to_regenerate(client, fake_ai):
    cid = new_conversation(client)
    response = client.post("/api/chat", json={"conversation_id": cid, "regenerate": True}, buffered=True)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "nothing_to_regenerate"


def test_rate_limit(app, client, fake_ai):
    app.extensions["rate_limiter"].limit = 2
    cid = new_conversation(client)
    assert chat(client, cid, "1").status_code == 200
    assert chat(client, cid, "2").status_code == 200
    third = chat(client, cid, "3")
    assert third.status_code == 429
    assert third.get_json()["error"]["code"] == "rate_limited"


def test_settings_roundtrip_and_validation(client):
    data = client.get("/api/settings").get_json()
    assert data["settings"] == {"theme": "dark", "response_style": "balanced"}
    assert "api_key" not in str(data).lower() and "test-key" not in str(data)
    assert data["ai"] == {"configured": True, "model": "test-model"}
    updated = client.put("/api/settings", json={"theme": "light", "response_style": "concise"})
    assert updated.get_json()["settings"] == {"theme": "light", "response_style": "concise"}
    assert 'data-theme="light"' in client.get("/").get_data(as_text=True)
    assert client.put("/api/settings", json={"theme": "neon"}).status_code == 400
    assert client.put("/api/settings", json={"unknown": "x"}).status_code == 400
    assert client.put("/api/settings", json={}).status_code == 400


def test_stopping_early_keeps_the_partial_reply(client, fake_ai):
    """Simulates the Stop button: the browser disconnects after the first chunk."""
    cid = new_conversation(client)
    response = client.post("/api/chat", json={"conversation_id": cid, "message": "Hi"})
    next(iter(response.response))  # read only the first chunk
    response.close()               # browser aborted the request
    messages = client.get(f"/api/conversations/{cid}").get_json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [("user", "Hi"), ("assistant", "Hello")]
