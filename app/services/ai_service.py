"""AI service layer. This is the ONLY module that talks to OpenAI.

It uses the official OpenAI Python SDK and the Responses API with streaming.
Errors from the SDK are translated into `AIServiceError` with a friendly
message; technical details are logged without secrets or message content.
"""
import logging
from collections.abc import Iterator

from flask import current_app
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

STYLE_HINTS = {
    "concise": "Keep answers short and direct unless the user asks for detail.",
    "balanced": "",
    "detailed": "Give thorough, step-by-step explanations with examples when helpful.",
}


class AIServiceError(Exception):
    """A problem talking to the AI provider, safe to show to the user."""

    def __init__(self, message: str, status: int = 502, code: str = "ai_error"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def is_configured(config) -> bool:
    key = (config.get("OPENAI_API_KEY") or "").strip()
    model = (config.get("OPENAI_MODEL") or "").strip()
    placeholder = key.lower().startswith("your-") or model.lower().startswith("your-")
    return bool(key and model) and not placeholder


def trim_history(messages: list[dict], max_messages: int, max_chars: int) -> list[dict]:
    """Keep the newest messages that fit the limits (always keeps the last one)."""
    kept, total = [], 0
    for msg in reversed(messages[-max_messages:]):
        total += len(msg["content"])
        if kept and total > max_chars:
            break
        kept.append(msg)
    return list(reversed(kept))


def _build_instructions(response_style: str) -> str:
    hint = STYLE_HINTS.get(response_style, "")
    return f"{current_app.config['SYSTEM_PROMPT']} {hint}".strip()


def translate_error(exc: OpenAIError) -> AIServiceError:
    """Map an SDK exception to a user-friendly AIServiceError."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status_code", None)
    # Log only the exception type and codes: messages may echo parts of a key.
    logger.warning("OpenAI error: type=%s status=%s code=%s", type(exc).__name__, status, code)
    model = current_app.config.get("OPENAI_MODEL", "")

    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return AIServiceError("OpenAI rejected the API key or its permissions. Check OPENAI_API_KEY in your .env file.", 502, "auth_failed")
    if isinstance(exc, RateLimitError):
        if code == "insufficient_quota":
            return AIServiceError("Your OpenAI account has no remaining quota. Check your plan and billing details.", 429, "insufficient_quota")
        return AIServiceError("OpenAI is rate limiting requests. Wait a moment and try again.", 429, "rate_limited")
    if isinstance(exc, NotFoundError):
        return AIServiceError(f"The model '{model}' is not available for your account. Change OPENAI_MODEL in .env and restart.", 502, "model_unavailable")
    if isinstance(exc, APITimeoutError):
        return AIServiceError("OpenAI took too long to respond. Try again.", 504, "timeout")
    if isinstance(exc, APIConnectionError):
        return AIServiceError("Could not reach OpenAI. Check your internet connection and try again.", 503, "network_error")
    if isinstance(exc, BadRequestError):
        return AIServiceError("OpenAI could not process this request. Check OPENAI_MODEL and try a shorter message.", 502, "bad_request_upstream")
    if isinstance(exc, APIStatusError) and (status or 0) >= 500:
        return AIServiceError("OpenAI is temporarily unavailable. Try again shortly.", 502, "upstream_unavailable")
    return AIServiceError("The AI service returned an unexpected error. Try again.", 502, "ai_error")


def stream_reply(history: list[dict], response_style: str = "balanced") -> Iterator[str]:
    """Start a streamed reply and return an iterator of text chunks.

    The request to OpenAI is made immediately, so configuration, authentication
    and model errors are raised here (before any response is sent to the browser).
    Errors that happen mid-stream are raised while iterating.
    """
    cfg = current_app.config
    if not is_configured(cfg):
        raise AIServiceError(
            "The AI is not configured yet. Add OPENAI_API_KEY and OPENAI_MODEL to your .env file, then restart the app.",
            503,
            "not_configured",
        )

    messages = trim_history(history, cfg["MAX_HISTORY_MESSAGES"], cfg["MAX_HISTORY_CHARS"])
    client = OpenAI(api_key=cfg["OPENAI_API_KEY"], timeout=cfg["OPENAI_TIMEOUT_SECONDS"], max_retries=2)
    try:
        stream = client.responses.create(
            model=cfg["OPENAI_MODEL"],
            instructions=_build_instructions(response_style),
            input=[{"role": m["role"], "content": m["content"]} for m in messages],
            max_output_tokens=cfg["MAX_OUTPUT_TOKENS"],
            stream=True,
            store=False,  # do not keep conversations on OpenAI's side
        )
    except OpenAIError as exc:
        raise translate_error(exc) from exc
    return _iter_text(stream)


def _iter_text(stream) -> Iterator[str]:
    try:
        for event in stream:
            kind = getattr(event, "type", "")
            if kind == "response.output_text.delta":
                yield event.delta
            elif kind == "response.incomplete":
                details = getattr(getattr(event, "response", None), "incomplete_details", None)
                if getattr(details, "reason", None) == "max_output_tokens":
                    yield "\n\n*(The reply was cut off because it reached the length limit.)*"
            elif kind == "response.failed":
                error = getattr(getattr(event, "response", None), "error", None)
                logger.warning("Response failed: code=%s", getattr(error, "code", None))
                raise AIServiceError("The model could not finish the reply. Try again.", 502, "response_failed")
            elif kind == "error":
                logger.warning("Stream error event: code=%s", getattr(event, "code", None))
                raise AIServiceError("OpenAI reported an error while writing the reply. Try again.", 502, "stream_error")
    except OpenAIError as exc:
        raise translate_error(exc) from exc
    finally:
        close = getattr(stream, "close", None)
        if close:
            close()
