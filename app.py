import os
import re
import uuid
import json
import tempfile
from pathlib import Path
from io import BytesIO

from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

import pdfplumber
import fitz  # PyMuPDF
from PIL import Image

from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dictionary-secret-key")

UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "dict_uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

SPANISH_VOICE_ID = "pNInz6obpgDQGcFmaJgB"
ENGLISH_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
TTS_MODEL        = "eleven_multilingual_v2"
TTS_STABILITY    = 0.75
TTS_SIMILARITY   = 0.85
TTS_SPEED        = 0.75


def parse_word_pairs(text):
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


def process_pdf(pdf_path, session_id):
    out_dir = os.path.join(UPLOAD_FOLDER, session_id)
    os.makedirs(out_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    page_words = []

    for i, page in enumerate(doc):
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.save(os.path.join(out_dir, f"page_{i}.jpg"), "JPEG", quality=85)

    doc.close()

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            page_words.append(parse_word_pairs(text))

    meta = {"num_pages": num_pages, "page_words": page_words}
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f)

    return meta


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
    pdf_dir = os.path.join(UPLOAD_FOLDER, session_id)
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, "source.pdf")
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
    data = request.get_json()
    api_key = data.get("api_key", "").strip()
    spanish  = data.get("spanish", "").strip()
    english  = data.get("english", "").strip()
    lang     = data.get("lang", "both")

    if not api_key:
        return jsonify({"error": "ElevenLabs API key required"}), 400

    try:
        client = ElevenLabs(api_key=api_key)
        vs = VoiceSettings(stability=TTS_STABILITY,
                           similarity_boost=TTS_SIMILARITY,
                           speed=TTS_SPEED)

        def synth(text, voice_id, lang_code):
            return b"".join(client.text_to_speech.convert(
                voice_id=voice_id, text=text,
                model_id=TTS_MODEL, voice_settings=vs,
                language_code=lang_code))

        chunks = []
        if lang in ("es", "both") and spanish:
            chunks.append(synth(spanish, SPANISH_VOICE_ID, "es"))
        if lang in ("en", "both") and english:
            chunks.append(synth(english, ENGLISH_VOICE_ID, "en"))

        return send_file(BytesIO(b"".join(chunks)),
                         mimetype="audio/mpeg", as_attachment=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
