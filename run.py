"""Entry point for local development: `python run.py`.

(This file is called run.py rather than app.py because the package folder is
already named `app/`; two things named `app` would be confusing.)
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])
