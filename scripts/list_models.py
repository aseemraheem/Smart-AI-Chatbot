"""Print the model IDs available to your API key.

Usage (from the project root, with the virtual environment active):
    python scripts/list_models.py

Pick a text/chat-capable model from the list and put it in `.env` as OPENAI_MODEL.
"""
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

load_dotenv()
key = os.environ.get("OPENAI_API_KEY", "").strip()
if not key or key.startswith("your-"):
    sys.exit("Set OPENAI_API_KEY in your .env file first.")

try:
    for model in sorted(OpenAI(api_key=key).models.list(), key=lambda m: m.id):
        print(model.id)
except OpenAIError as exc:
    sys.exit(f"Could not list models: {type(exc).__name__}")
