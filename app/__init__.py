"""Application factory for Smart AI Chatbot."""
import logging
import os
import secrets
from pathlib import Path

from flask import Flask

from config import Config


def _load_secret_key(instance_path: Path) -> str:
    """Use a persistent random key so sessions survive restarts.

    The key is stored in instance/.secret_key (git-ignored). For production,
    set SECRET_KEY in the environment instead.
    """
    key_file = instance_path / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)  # templates/ and static/ are resolved inside app/
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_secret_key(Path(app.instance_path))

    from app import errors, security
    from app.database import db
    from app.routes.chat import bp as chat_bp

    db.init_app(app)
    security.init_app(app)
    errors.init_app(app)
    app.register_blueprint(chat_bp)
    return app
