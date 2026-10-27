"""HTTP routes: the home page and the JSON API."""
import json
import logging
import re
import sqlite3

from flask import Blueprint, Response, current_app, jsonify, render_template, request, stream_with_context

from app.database import queries
from app.database.db import get_db
from app.errors import ApiError
from app.security import get_csrf_token
from app.services import ai_service
from app.services.ai_service import AIServiceError
from config import APP_VERSION

bp = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)

CONVERSATION_ID_RE = re.compile(r"[0-9a-f]{32}")


# --- Validation helpers -------------------------------------------------
def _json_body() -> dict:
    data = request.get_json(silent=True)  # None when missing or malformed
    if not isinstance(data, dict):
        raise ApiError("Request body must be a valid JSON object.", 400, "invalid_json")
    return data


def _conversation_id(value) -> str:
    if not isinstance(value, str) or not CONVERSATION_ID_RE.fullmatch(value):
        raise ApiError("Invalid conversation ID.", 400, "invalid_conversation_id")
    return value


def _require_conversation(conversation_id: str) -> dict:
    conv = queries.get_conversation(get_db(), _conversation_id(conversation_id))
    if conv is None:
        raise ApiError("Conversation not found.", 404, "not_found")
    return conv


def _clean_title(value) -> str:
    if not isinstance(value, str):
        raise ApiError("Title must be text.", 400, "invalid_title")
    title = re.sub(r"\s+", " ", value).strip()
    if not title:
        raise ApiError("Title cannot be empty.", 400, "invalid_title")
    if len(title) > current_app.config["MAX_TITLE_CHARS"]:
        raise ApiError(f"Title must be {current_app.config['MAX_TITLE_CHARS']} characters or fewer.", 400, "invalid_title")
    return title


def _clean_message(value) -> str:
    if not isinstance(value, str):
        raise ApiError("Message must be text.", 400, "invalid_message")
    text = value.strip()
    if not text:
        raise ApiError("Message cannot be empty.", 400, "empty_message")
    limit = current_app.config["MAX_MESSAGE_CHARS"]
    if len(text) > limit:
        raise ApiError(f"Message is too long (maximum {limit} characters).", 400, "message_too_long")
    return text


# --- Pages --------------------------------------------------------------
@bp.get("/")
def index():
    settings = queries.get_settings(get_db())
    return render_template(
        "index.html",
        csrf_token=get_csrf_token(),
        theme=settings["theme"],
        max_chars=current_app.config["MAX_MESSAGE_CHARS"],
        version=APP_VERSION,
    )


# --- Conversations ------------------------------------------------------
@bp.get("/api/conversations")
def list_conversations():
    search = request.args.get("q", "").strip()[:100]
    return jsonify({"conversations": queries.list_conversations(get_db(), search or None)})


@bp.post("/api/conversations")
def create_conversation():
    data = _json_body()
    title = _clean_title(data["title"]) if "title" in data else queries.DEFAULT_TITLE
    return jsonify({"conversation": queries.create_conversation(get_db(), title)}), 201


@bp.get("/api/conversations/<conversation_id>")
def get_conversation(conversation_id):
    conv = _require_conversation(conversation_id)
    return jsonify({"conversation": conv, "messages": queries.get_messages(get_db(), conv["id"])})


@bp.patch("/api/conversations/<conversation_id>")
def rename_conversation(conversation_id):
    conv = _require_conversation(conversation_id)
    title = _clean_title(_json_body().get("title"))
    queries.rename_conversation(get_db(), conv["id"], title)
    return jsonify({"conversation": queries.get_conversation(get_db(), conv["id"])})


@bp.delete("/api/conversations/<conversation_id>")
def delete_conversation(conversation_id):
    conv = _require_conversation(conversation_id)
    queries.delete_conversation(get_db(), conv["id"])
    return jsonify({"deleted": True})


# --- Settings -----------------------------------------------------------
def _settings_payload():
    cfg = current_app.config
    return {
        "settings": queries.get_settings(get_db()),
        "options": {k: sorted(v) for k, v in queries.ALLOWED_SETTINGS.items()},
        # Never include the key itself: only whether it is configured.
        "ai": {"configured": ai_service.is_configured(cfg), "model": cfg["OPENAI_MODEL"] or None},
        "limits": {"max_message_chars": cfg["MAX_MESSAGE_CHARS"]},
    }


@bp.get("/api/settings")
def get_settings():
    return jsonify(_settings_payload())


@bp.put("/api/settings")
def update_settings():
    data = _json_body()
    if not data:
        raise ApiError("No settings provided.", 400, "invalid_settings")
    for key, value in data.items():
        if key not in queries.ALLOWED_SETTINGS or value not in queries.ALLOWED_SETTINGS[key]:
            raise ApiError(f"Unsupported setting or value: {key}.", 400, "invalid_settings")
    for key, value in data.items():
        queries.set_setting(get_db(), key, value)
    return jsonify(_settings_payload())


# --- Chat (streaming) ---------------------------------------------------
def _event(payload: dict) -> str:
    """One newline-delimited JSON event for the browser."""
    return json.dumps(payload, ensure_ascii=False) + "\n"


@bp.post("/api/chat")
def chat():
    """Send a message (or regenerate the last reply) and stream the answer.

    Body: {"conversation_id": str, "message": str}  or
          {"conversation_id": str, "regenerate": true}
    Validation and AI start-up errors return normal JSON errors. Once streaming
    has begun, problems are sent as an {"type": "error"} event.
    """
    cfg = current_app.config
    db = get_db()
    data = _json_body()
    conv = _require_conversation(data.get("conversation_id"))
    cid = conv["id"]

    regenerate = data.get("regenerate", False)
    if not isinstance(regenerate, bool):
        raise ApiError("'regenerate' must be true or false.", 400, "invalid_request")
    # Clients may only send user messages; assistant/system roles are never accepted.
    if data.get("role", "user") != "user":
        raise ApiError("Invalid message role.", 400, "invalid_role")

    new_text = None if regenerate else _clean_message(data.get("message"))

    if not current_app.extensions["rate_limiter"].allow(request.remote_addr or "local"):
        raise ApiError("Too many requests. Please wait a moment and try again.", 429, "rate_limited")

    recent = queries.get_recent_messages(db, cid, cfg["MAX_HISTORY_MESSAGES"] + 1)
    old_assistant_id = None
    if regenerate:
        if recent and recent[-1]["role"] == "assistant":
            old_assistant_id = recent[-1]["id"]
            recent = recent[:-1]
        if not recent or recent[-1]["role"] != "user":
            raise ApiError("There is no message to regenerate a reply for.", 400, "nothing_to_regenerate")
        history = recent
    else:
        history = recent + [{"role": "user", "content": new_text}]

    # Start the AI request BEFORE saving anything, so a failure (bad key, no
    # network, ...) leaves the conversation untouched and the user can retry.
    style = queries.get_settings(db)["response_style"]
    deltas = ai_service.stream_reply(history, style)

    if old_assistant_id is not None:
        queries.delete_message(db, old_assistant_id)
    if new_text is not None:
        queries.add_message(db, cid, "user", new_text)
        if conv["title"] == queries.DEFAULT_TITLE:
            conv["title"] = queries.make_title(new_text)
            queries.rename_conversation(db, cid, conv["title"])

    def generate():
        # The view's connection is closed once the view returns, but this generator
        # keeps running while streaming. stream_with_context gives it its own app
        # context, so ask for a fresh connection here instead of reusing `db`.
        gen_db = get_db()
        parts: list[str] = []
        saved = False
        try:
            for delta in deltas:
                parts.append(delta)
                yield _event({"type": "delta", "text": delta})
            text = "".join(parts).strip()
            if not text:
                raise AIServiceError("The model returned an empty reply. Try again.", 502, "empty_response")
            message = queries.add_message(gen_db, cid, "assistant", text)
            saved = True
            yield _event({"type": "done", "message": message, "title": conv["title"]})
        except AIServiceError as exc:
            yield _event({"type": "error", "message": exc.message, "code": exc.code})
        except Exception:  # unexpected: log details, tell the browser something generic
            logger.exception("Unexpected error while streaming a reply")
            yield _event({"type": "error", "message": "Something went wrong while writing the reply.", "code": "server_error"})
        finally:
            # Also runs when the browser disconnects (Stop button): keep what was written.
            if not saved and "".join(parts).strip():
                try:
                    queries.add_message(gen_db, cid, "assistant", "".join(parts).strip())
                except sqlite3.Error:
                    logger.exception("Could not save partial reply")
            close = getattr(deltas, "close", None)
            if close:
                close()

    response = Response(stream_with_context(generate()), mimetype="application/x-ndjson")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # disable proxy buffering
    return response
