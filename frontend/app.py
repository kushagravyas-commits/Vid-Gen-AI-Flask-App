import os
import json
import requests
from flask import Flask, render_template, request

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

app = Flask(__name__)


@app.get("/")
def index():
    # Fetch styles + languages from backend so frontend always stays in sync
    styles = []
    languages = {}
    try:
        styles = requests.get(f"{BACKEND_URL}/api/v1/meta/styles", timeout=5).json().get("styles", [])
    except Exception:
        pass

    try:
        languages = requests.get(f"{BACKEND_URL}/api/v1/meta/languages", timeout=5).json().get("languages", {})
    except Exception:
        pass

    return render_template(
        "index.html",
        backend_url=BACKEND_URL,
        styles=styles,
        languages=languages,
        languages_json=json.dumps(languages),
        styles_json=json.dumps(styles),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
