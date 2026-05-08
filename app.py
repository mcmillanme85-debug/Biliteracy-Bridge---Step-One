"""
Digital Dictionary — Flask Web App
====================================
Web version of the PDF wordbank tool with ElevenLabs TTS.
Deploy on Render.com (free tier) and connect to your Hostinger domain.
"""

import os
import re
import uuid
import json
import tempfile
import threading
from pathlib import Path
from io import BytesIO
from flask import (
    Flask, request, jsonify, send_file,
    render_template, session
)
from werkzeug.utils import secure_filename
import pdfplumber
from pdf2image import convert_from_path
from PIL import Image
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dictionary-secret-key-change-me")

UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "dict_uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

MAX_CONTENT_LENGTH = 50 * 1024 * 1024   # 50 MB upload limit
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# ─────────────────────────────────────────────
# TTS CONFIG
# ─────────────────────────────────────────────

SPANISH_VOICE_ID = "pNInz6obpgDQGcFmaJgB"   # Adam
ENGLISH_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"   # Bella
TTS_MODEL        = "eleven_multilingual_v2"
TTS_STABILITY    = 0.75
TTS_SIMILARITY   = 0.85
TTS_SPEED        = 0.75                       # slower pronunciation

# ─────────────────────────────────────────────
# WORD-PAIR PARSER
# ─────────────────────────────────────────────

def parse_word_pairs(text: str) -> list[dict]:
    """
    Heuristic bilingual pair parser.
    Handles: 2-space columns, dash, pipe, slash, numbered lists.
    Returns [{es, en}, ...]
    """
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^\d+[.\)]\s*", "", line)
        for sep in (r"\s{2,}", r"\s*[-|/–—]\s*", r"\t"):
            parts = re.split(sep, line, maxsplit=1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                pairs.append({"es": parts[0].strip(), "en": parts[1].strip()})
                break
    return pairs

# ─────────────────────────────────────────────
# PDF PROCESSING
# ─────────────────────────────────────────────

def process_pdf(pdf_path: str, session_id: str) -> dict:
    """
    Render pages to images, extract word pairs.
    Stores results in UPLOAD_FOLDER/<session_id>/
    Returns metadata dict.
    """
    out_dir = os.path.join(UPLOAD_FOLDER, session_id)
    os.makedirs(out_dir, exist_ok=True)

    # Render pages
    images = convert_from_path(pdf_path, dpi=150)
    num_pages = len(images)

    page_words = []
    for i, img in enumerate(images):
        # Save page image as JPEG
        img_path = os.path.join(out_dir, f"page_{i}.jpg")
        img.save(img_path, "JPEG", quality=85)

    # Extract words
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            page_words.append(parse_word_pairs(text))

    # Save metadata
    meta = {"num_pages": num_pages, "page_words": page_words}
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f)

    return meta

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    if "pdf" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["pdf"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    session_id = str(uuid.uuid4())
    pdf_path = os.path.join(UPLOAD_FOLDER, session_id, "source.pdf")
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    file.save(pdf_path)

    try:
        meta = process_pdf(pdf_path, session_id)
        return jsonify({
            "session_id": session_id,
            "num_pages": meta["num_pages"],
            "total_words": sum(len(w) for w in meta["page_words"])
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/page/<session_id>/<int:page_num>")
def get_page_image(session_id, page_num):
    img_path = os.path.join(UPLOAD_FOLDER, session_id, f"page_{page_num}.jpg")
    if not os.path.exists(img_path):
        return jsonify({"error": "Page not found"}), 404
    return send_file(img_path, mimetype="image/jpeg")


@app.route("/words/<session_id>/<int:page_num>")
def get_page_words(session_id, page_num):
    meta_path = os.path.join(UPLOAD_FOLDER, session_id, "meta.json")
    if not os.path.exists(meta_path):
        return jsonify({"error": "Session not found"}), 404
    with open(meta_path) as f:
        meta = json.load(f)
    words = meta["page_words"][page_num] if page_num < meta["num_pages"] else []
    return jsonify({"words": words})


@app.route("/speak", methods=["POST"])
def speak():
    """
    Body: { api_key, spanish, english, lang }
    lang: "es" | "en" | "both"
    Returns: audio/mpeg stream
    """
    data = request.get_json()
    api_key = data.get("api_key", "").strip()
    spanish = data.get("spanish", "").strip()
    english = data.get("english", "").strip()
    lang    = data.get("lang", "both")

    if not api_key:
        return jsonify({"error": "ElevenLabs API key required"}), 400
    if not spanish and not english:
        return jsonify({"error": "No word provided"}), 400

    try:
        client = ElevenLabs(api_key=api_key)
        voice_settings = VoiceSettings(
            stability=TTS_STABILITY,
            similarity_boost=TTS_SIMILARITY,
            speed=TTS_SPEED,
        )

        audio_chunks = []

        def synthesize(text, voice_id, language_code):
            gen = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=TTS_MODEL,
                voice_settings=voice_settings,
                language_code=language_code,
            )
            return b"".join(gen)

        if lang in ("es", "both") and spanish:
            audio_chunks.append(synthesize(spanish, SPANISH_VOICE_ID, "es"))

        if lang in ("en", "both") and english:
            # Small silence gap (0.5s of silence at 44100Hz mono MP3 ≈ 4KB)
            # We'll just concatenate — browser handles it fine
            audio_chunks.append(synthesize(english, ENGLISH_VOICE_ID, "en"))

        combined = b"".join(audio_chunks)
        return send_file(
            BytesIO(combined),
            mimetype="audio/mpeg",
            as_attachment=False
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
