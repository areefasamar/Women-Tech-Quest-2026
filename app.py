"""
app.py – Flask server serving ui/index.html with /api/decode and /api/ask endpoints.

Keeps the pipeline in src/ - this file is just a thin HTTP layer.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, abort

from src.level1 import extract_level1
from src.facts import extract_facts
from src.level2 import answer_questions
from src.image_prep import prepare_images
from src.pii_guard import scrub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)

UI_DIR = Path(__file__).parent / "ui"

# In-memory store for per-upload facts (keyed by image hash)
_store: dict[str, dict] = {}   # hash → {l1, facts, images}

SAMPLE_QUESTIONS = [
    {"question_id": "Q1", "question": "How much of my bill is taxes?"},
    {"question_id": "Q2", "question": "What is the cost per unit of electricity?"},
    {"question_id": "Q3", "question": "What happens if I pay after the due date?"},
    {"question_id": "Q4", "question": "How does my usage compare to last month?"},
    {"question_id": "Q5", "question": "What are my arrears or previous dues?"},
]


@app.route("/")
def index():
    return send_from_directory(UI_DIR, "index.html")


@app.route("/ui/<path:filename>")
def ui_static(filename: str):
    return send_from_directory(UI_DIR, filename)


@app.route("/api/decode", methods=["POST"])
def api_decode():
    """
    POST multipart/form-data with field 'image' (the bill photo).
    Returns: { "bill_id": str, "level1": {...}, "answers": {"Q1": "...", ...} }
    """
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    file = request.files["image"]
    image_bytes = file.read()
    if not image_bytes:
        return jsonify({"error": "Empty image"}), 400

    image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
    bill_id = f"upload_{image_hash}"

    # Save to temp file for pipeline
    suffix = Path(file.filename or "bill.jpg").suffix.lower() or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)

    try:
        # Level 1
        l1 = extract_level1(tmp_path, use_cache=True)
        # Facts
        facts = extract_facts(tmp_path, use_cache=True)
        # Prepare images (for Level 2)
        full_bytes, top_bytes, bot_bytes = prepare_images(tmp_path)
        bill_images = [full_bytes, top_bytes, bot_bytes]

        # Cache for /api/ask
        _store[bill_id] = {"l1": l1, "facts": facts, "images": bill_images}

        # Level 2 – default questions
        answers = answer_questions(
            bill_id=bill_id,
            questions=SAMPLE_QUESTIONS,
            l1=l1,
            facts=facts,
            bill_images=bill_images,
            use_cache=True,
        )

    finally:
        tmp_path.unlink(missing_ok=True)

    return jsonify({
        "bill_id": bill_id,
        "level1": l1,
        "answers": answers,
    })


@app.route("/api/ask", methods=["POST"])
def api_ask():
    """
    POST JSON: { "bill_id": "upload_xxxx", "question": "..." }
    Returns: { "answer": "..." }
    Reuses stored facts for that upload.
    """
    data = request.get_json(force=True, silent=True) or {}
    bill_id = data.get("bill_id", "")
    question = str(data.get("question", "")).strip()

    if not question:
        return jsonify({"error": "Empty question"}), 400

    stored = _store.get(bill_id)
    if not stored:
        return jsonify({"error": "Bill not found. Please decode a bill first."}), 404

    l1 = stored["l1"]
    facts = stored["facts"]
    bill_images = stored["images"]

    answers = answer_questions(
        bill_id=bill_id,
        questions=[{"question_id": "Quser", "question": question}],
        l1=l1,
        facts=facts,
        bill_images=bill_images,
        use_cache=False,  # user questions are not cached
    )
    answer = scrub(answers.get("Quser", "This information is not shown on this bill."))
    return jsonify({"answer": answer})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("Starting Bill Decoder server on http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
