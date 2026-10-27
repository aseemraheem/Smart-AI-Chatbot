# Smart AI Chatbot

A ChatGPT-inspired AI chatbot web app built with **Flask**, **SQLite** and the **OpenAI Responses API**. It runs locally, saves your conversations in a database, streams answers as they are written, and renders Markdown and syntax-highlighted code.

> Single-user local app. There are no accounts or logins, so do not expose it to the internet as-is (see [Security notes](#security-notes)).

## Screenshots

Real screenshots have not been added yet. After running the app, save your own images in `docs/screenshots/` and replace this table.

| View | File to add | Status |
|---|---|---|
| Welcome screen (dark) | `docs/screenshots/welcome-dark.png` | placeholder, not added yet |
| Conversation with code block | `docs/screenshots/chat-code.png` | placeholder, not added yet |
| Light theme + mobile layout | `docs/screenshots/light-mobile.png` | placeholder, not added yet |

## Features

**Implemented in this version**

- Multi-turn chat using the official OpenAI Python SDK and the Responses API, with **streamed** replies
- **Stop** button (keeps the text written so far) and **Regenerate** button
- Conversations saved in SQLite: create, reopen after refresh, rename, delete (with confirmation), search titles *and* message text
- Automatic conversation titles from the first message
- Markdown rendering (headings, lists, links, tables, code), syntax highlighting, **copy** buttons for replies and code blocks
- Dark theme by default plus a light theme; response-style setting (concise / balanced / detailed)
- Responsive layout with a collapsible sidebar on mobile; keyboard-accessible controls
- Clear errors for a missing key, invalid key, rate limits, no quota, unavailable model and network failures
- Server-side validation, CSRF protection, a per-IP rate limit, strict Content-Security-Policy, safe Markdown rendering
- `pytest` suite with the OpenAI API fully mocked

**Not implemented yet**

- Document (PDF) Q&A, see [Planned improvements](#planned-improvements)
- User accounts / authentication

## Technology stack

Python 3.10+, Flask, OpenAI Python SDK (Responses API), SQLite, python-dotenv, pytest, and vanilla HTML/CSS/JavaScript. The front end bundles three small libraries in `app/static/vendor/` (no CDN needed, works offline): [marked](https://github.com/markedjs/marked) (MIT), [DOMPurify](https://github.com/cure53/DOMPurify) (Apache-2.0/MPL-2.0) and [highlight.js](https://highlightjs.org/) (BSD-3-Clause). Their license files are in the same folder.

## Project structure

```
Smart-AI-Chatbot/
├── run.py                  # start the app (python run.py)
├── config.py               # settings read from environment / .env
├── requirements.txt
├── .env.example            # placeholders only: copy to .env
├── app/
│   ├── __init__.py         # application factory
│   ├── errors.py           # JSON error handling
│   ├── security.py         # CSRF, rate limiter, security headers
│   ├── routes/chat.py      # page + JSON API + streaming chat endpoint
│   ├── services/ai_service.py   # the only code that talks to OpenAI
│   ├── database/db.py      # connection + schema
│   ├── database/queries.py # conversation / message / settings queries
│   ├── templates/index.html
│   └── static/{css,js,images,vendor}
├── scripts/list_models.py  # prints model IDs your key can use
├── tests/                  # pytest suite (OpenAI is mocked)
├── instance/               # local database lives here (git-ignored)
└── docs/screenshots/
```

`run.py` is used instead of `app.py` because the package folder is already called `app/`.

## Prerequisites

- Windows 10/11, [Python 3.10 or newer](https://www.python.org/downloads/) (tick **Add python.exe to PATH** in the installer)
- [VS Code](https://code.visualstudio.com/) (optional but recommended) and [Git](https://git-scm.com/download/win)
- An OpenAI API key with API access/billing enabled (the interface opens without one, but replies need it)

## Windows setup (PowerShell)

Open the project folder in VS Code (**File → Open Folder**), then open a terminal (**Terminal → New Terminal**, PowerShell). Or from PowerShell: `cd path\to\Smart-AI-Chatbot`.

```powershell
# 1. Create the virtual environment
py -m venv .venv

# 2. Activate it (your prompt should start with (.venv))
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
python -m pip install -r requirements.txt

# 4. Create your private settings file
Copy-Item .env.example .env
```

### Configure your API key and model

Open `.env` in VS Code and replace the placeholders:

```
OPENAI_API_KEY=paste-your-own-key-here
OPENAI_MODEL=paste-a-model-id-here
```

Model names change over time, so none is hard-coded. To see which model IDs **your** key can use:

```powershell
python scripts/list_models.py
```

Pick a text/chat-capable model from the list and paste its ID into `OPENAI_MODEL`. Keep `.env` private: it is already in `.gitignore`.

### Run the app

```powershell
python run.py
```

Open <http://127.0.0.1:5000> in your browser. Stop the server with `Ctrl + C`. After editing `.env`, restart the app. For auto-reload while developing, set `FLASK_DEBUG=true` in `.env`.

### Run the tests

```powershell
python -m pytest
```

No API key or internet connection is needed because the OpenAI API is mocked.

## Publish to GitHub

1. Create an empty repository on github.com (no README/license; you already have a README).
2. In the project terminal:

```powershell
git init
git add .
git status          # check that .env and .venv are NOT listed
git commit -m "Initial commit: Smart AI Chatbot"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/Smart-AI-Chatbot.git
git push -u origin main
```

If you ever commit a real key by accident, **revoke it immediately** in the OpenAI dashboard and create a new one; deleting the file later does not remove it from Git history.

## Troubleshooting

| Problem | Fix |
|---|---|
| `py` is not recognized | Reinstall Python and tick *Add python.exe to PATH*, or try `python -m venv .venv`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again. |
| `ModuleNotFoundError` | The virtual environment is not active, or dependencies are missing: activate it and rerun the install command. |
| Banner says the AI is not configured | `OPENAI_API_KEY` / `OPENAI_MODEL` are missing or still placeholders in `.env`. Fix and restart the app. |
| "OpenAI rejected the API key" | The key is wrong, revoked, or from a different project. Create a new one. |
| "model … is not available" | Run `python scripts/list_models.py` and choose an ID from the list. |
| "no remaining quota" | Check your OpenAI plan and billing page. |
| "Security check failed" (403) | Reload the page; the session cookie expired or was cleared. |
| `Address already in use` | Another program uses port 5000. Set `PORT=5001` in `.env`. |
| Replies get cut off | Raise `MAX_OUTPUT_TOKENS` in `.env` (some models count reasoning tokens in this limit). |

## Security notes

- Secrets live only in `.env` (git-ignored). The key is never sent to the browser or returned by any endpoint, and is not logged.
- All SQL is parameterized. Conversation IDs and roles are validated; the browser can only submit `user` messages.
- State-changing API calls require a CSRF token. Request size, message length, history length and output length are limited, and chat requests are rate limited per IP (in memory, default 20/minute).
- Assistant Markdown is sanitized with DOMPurify before display; user text is inserted as plain text. A strict Content-Security-Policy blocks inline scripts and remote images.
- `store=False` is sent so OpenAI is asked not to retain the conversation. Your messages are still sent to OpenAI to produce replies.
- Conversations are stored unencrypted in `instance/chatbot.db`. Do not put sensitive information in them.
- Debug mode is off unless `FLASK_DEBUG=true`. The Flask development server is **not** a production server. This app has no login, so deploying it publicly would let anyone read the conversations and spend your API credit. Before any public deployment you would need authentication, per-user data isolation (with proper password hashing and session security), HTTPS (`SESSION_COOKIE_SECURE=true`), a shared rate limiter (for example Redis-backed) and a production WSGI server such as Waitress on Windows (`waitress-serve --call app:create_app`) or Gunicorn on Linux.

## Planned improvements

1. **Document Q&A (next milestone):** PDF upload with size limit, type validation and safe temporary storage; text extraction with PyMuPDF (handling scanned, malformed and encrypted PDFs); chunking and retrieval; answers grounded in the retrieved text. Uploaded documents must be treated as untrusted data, never as instructions. The `messages`/`conversations` schema and `ai_service` are structured so this can be added without a rewrite.
2. Authentication with per-user conversations
3. Export/import conversations; edit a previous message
4. Token-usage display and context summarisation for long chats

## License

Suggested license: **MIT** (permissive, common for portfolio projects). *This is a suggestion to confirm, not a decision.* If you choose it, add a `LICENSE` file with your name and the year. Third-party libraries in `app/static/vendor/` keep their own licenses.
