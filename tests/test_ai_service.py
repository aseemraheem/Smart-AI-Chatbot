"""Tests for the AI service layer using fake OpenAI clients (no network)."""
import pytest

try:  # newer openai SDKs use httpx2, older ones use httpx
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx


from openai import APIConnectionError, AuthenticationError, NotFoundError, RateLimitError

from app.services import ai_service
from app.services.ai_service import AIServiceError, trim_history


def _status_error(cls, status, body=None):
    request = httpx.Request("POST", "https://example.invalid/v1/responses")
    response = httpx.Response(status, request=request)
    return cls("upstream message that must never be shown", response=response, body=body)


class FakeEvent:
    def __init__(self, type, **kw):
        self.type = type
        self.__dict__.update(kw)


def fake_openai(create):
    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = type("R", (), {"create": staticmethod(create)})()
    return FakeClient


@pytest.mark.parametrize("make_exc,status,code", [
    (lambda: _status_error(AuthenticationError, 401), 502, "auth_failed"),
    (lambda: _status_error(RateLimitError, 429, {"code": "insufficient_quota"}), 429, "insufficient_quota"),
    (lambda: _status_error(RateLimitError, 429, {"code": "rate_limit_exceeded"}), 429, "rate_limited"),
    (lambda: _status_error(NotFoundError, 404), 502, "model_unavailable"),
    (lambda: APIConnectionError(request=httpx.Request("POST", "https://example.invalid")), 503, "network_error"),
])
def test_sdk_errors_become_friendly_errors(app, monkeypatch, make_exc, status, code):
    def create(**kwargs):
        raise make_exc()

    monkeypatch.setattr(ai_service, "OpenAI", fake_openai(create))
    with app.app_context(), pytest.raises(AIServiceError) as info:
        ai_service.stream_reply([{"role": "user", "content": "hi"}])
    assert (info.value.status, info.value.code) == (status, code)
    assert "must never be shown" not in info.value.message


def test_request_uses_responses_api_with_configured_model(app, monkeypatch):
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return iter([FakeEvent("response.output_text.delta", delta="Hi"),
                     FakeEvent("response.completed")])

    monkeypatch.setattr(ai_service, "OpenAI", fake_openai(create))
    with app.app_context():
        chunks = list(ai_service.stream_reply([{"role": "user", "content": "hello"}], "concise"))
    assert chunks == ["Hi"]
    assert seen["model"] == "test-model" and seen["stream"] is True and seen["store"] is False
    assert seen["input"] == [{"role": "user", "content": "hello"}]
    assert "short and direct" in seen["instructions"]


def test_truncated_reply_adds_notice(app, monkeypatch):
    details = type("D", (), {"reason": "max_output_tokens"})()
    response = type("Resp", (), {"incomplete_details": details})()
    events = [FakeEvent("response.output_text.delta", delta="Part"), FakeEvent("response.incomplete", response=response)]
    monkeypatch.setattr(ai_service, "OpenAI", fake_openai(lambda **kw: iter(events)))
    with app.app_context():
        text = "".join(ai_service.stream_reply([{"role": "user", "content": "x"}]))
    assert text.startswith("Part") and "cut off" in text


def test_failed_response_event_raises(app, monkeypatch):
    events = [FakeEvent("response.failed", response=None)]
    monkeypatch.setattr(ai_service, "OpenAI", fake_openai(lambda **kw: iter(events)))
    with app.app_context(), pytest.raises(AIServiceError):
        list(ai_service.stream_reply([{"role": "user", "content": "x"}]))


@pytest.mark.parametrize("key,model", [("", "m"), ("k", ""), ("your-api-key-here", "m"), ("k", "your-model-name-here")])
def test_unconfigured_is_detected(app, key, model):
    app.config.update(OPENAI_API_KEY=key, OPENAI_MODEL=model)
    with app.app_context(), pytest.raises(AIServiceError) as info:
        ai_service.stream_reply([{"role": "user", "content": "x"}])
    assert info.value.code == "not_configured"


def test_trim_history_limits_count_and_size():
    msgs = [{"role": "user", "content": "x" * 10} for _ in range(10)]
    assert len(trim_history(msgs, 4, 1000)) == 4
    assert len(trim_history(msgs, 10, 35)) == 3
    assert len(trim_history([{"role": "user", "content": "x" * 999}], 5, 10)) == 1  # always keeps the last
