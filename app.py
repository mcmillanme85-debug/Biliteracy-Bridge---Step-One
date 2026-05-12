import os, json, uuid, re, csv, io
from pathlib import Path
from io import BytesIO
from functools import wraps
from flask import (Flask, request, jsonify, send_file,
                   render_template, session, redirect, url_for, abort)
import fitz
from PIL import Image
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "biliteracy-bridge-secret-2025")

DATA_DIR   = Path("data")
PDFS_DIR   = DATA_DIR / "pdfs"
PAGES_DIR  = DATA_DIR / "pages"
for d in [DATA_DIR, PDFS_DIR, PAGES_DIR]:
    d.mkdir(exist_ok=True)

BOOKS_FILE        = DATA_DIR / "books.json"
ELEVENLABS_KEY    = os.environ.get("ELEVENLABS_API_KEY", "")
ADMIN_PASSWORD    = os.environ.get("ADMIN_PASSWORD", "")

SPANISH_VOICE_ID  = os.environ.get("SPANISH_VOICE_ID", "2Lb1en5ujrODDIqmp7F3")  # Jhenny
ENGLISH_VOICE_ID  = os.environ.get("ENGLISH_VOICE_ID", "2EUn20N7uqcXUxqGrJEF")  # Britney
TTS_MODEL         = "eleven_multilingual_v2"
TTS_STABILITY     = 0.80
TTS_SIMILARITY    = 0.85
TTS_SPEED         = 0.75

# ── Data helpers ─────────────────────────────────────────────────

def load_books():
    if BOOKS_FILE.exists():
        with open(BOOKS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_books(books):
    with open(BOOKS_FILE, "w", encoding="utf-8") as f:
        json.dump(books, f, indent=2, ensure_ascii=False)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ── Public ────────────────────────────────────────────────────────

@app.route("/book/<book_id>")
def book_page(book_id):
    books = load_books()
    book  = books.get(book_id)
    if not book:
        abort(404)
    return render_template("book.html", book=book, book_id=book_id)

@app.route("/api/book/<book_id>/page/<int:page_num>/image")
def page_image(book_id, page_num):
    img_path = PAGES_DIR / book_id / f"page_{page_num}.jpg"
    if not img_path.exists():
        abort(404)
    return send_file(img_path, mimetype="image/jpeg")

@app.route("/api/book/<book_id>/page/<int:page_num>/content")
def page_content(book_id, page_num):
    books = load_books()
    book  = books.get(book_id)
    if not book:
        return jsonify({"error": "Book not found"}), 404
    pages = book.get("pages", [])
    if page_num >= len(pages):
        return jsonify({"content": [], "type": "words", "teacher_note": ""})
    pg = pages[page_num]
    return jsonify({
        "content":      pg.get("content", []),
        "type":         pg.get("type", "words"),
        "teacher_note": pg.get("teacher_note", "")
    })

@app.route("/api/speak", methods=["POST"])
def speak():
    data    = request.get_json()
    spanish = data.get("spanish", "").strip()
    english = data.get("english", "").strip()
    lang    = data.get("lang", "both")

    if not ELEVENLABS_KEY:
        return jsonify({"error": "Audio service not configured"}), 400

    try:
        client = ElevenLabs(api_key=ELEVENLABS_KEY)
        vs     = VoiceSettings(stability=TTS_STABILITY,
                               similarity_boost=TTS_SIMILARITY,
                               speed=TTS_SPEED)

        def synth(text, voice_id):
            return b"".join(client.text_to_speech.convert(
                voice_id=voice_id, text=text,
                model_id=TTS_MODEL, voice_settings=vs))

        chunks = []
        if lang in ("es", "both") and spanish:
            chunks.append(synth(spanish, SPANISH_VOICE_ID))
        if lang in ("en", "both") and english:
            chunks.append(synth(english, ENGLISH_VOICE_ID))

        return send_file(BytesIO(b"".join(chunks)), mimetype="audio/mpeg")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Admin ─────────────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Incorrect password. Please try again."
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    books = load_books()
    return render_template("admin_dashboard.html", books=books)

@app.route("/admin/book/new", methods=["GET", "POST"])
@admin_required
def admin_new_book():
    error = None
    if request.method == "POST":
        title   = request.form.get("title", "").strip()
        book_id = request.form.get("book_id", "").strip().lower()
        book_id = re.sub(r"[^a-z0-9\-]", "-", book_id).strip("-")
        if not title or not book_id:
            error = "Both fields are required."
        else:
            books = load_books()
            if book_id in books:
                error = "That URL ID is already in use. Choose another."
            else:
                books[book_id] = {"title": title, "num_pages": 0, "pages": []}
                save_books(books)
                return redirect(url_for("admin_book", book_id=book_id))
    return render_template("admin_new_book.html", error=error)

@app.route("/admin/book/<book_id>")
@admin_required
def admin_book(book_id):
    books = load_books()
    book  = books.get(book_id)
    if not book:
        abort(404)
    return render_template("admin_book.html", book=book, book_id=book_id)

@app.route("/admin/book/<book_id>/upload-pdf", methods=["POST"])
@admin_required
def admin_upload_pdf(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify({"error": "Book not found"}), 404
    if "pdf" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["pdf"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "PDF files only"}), 400

    pdf_path = PDFS_DIR / f"{book_id}.pdf"
    file.save(pdf_path)
    pages_dir = PAGES_DIR / book_id
    pages_dir.mkdir(exist_ok=True)

    doc       = fitz.open(str(pdf_path))
    num_pages = len(doc)
    for i, page in enumerate(doc):
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.save(pages_dir / f"page_{i}.jpg", "JPEG", quality=85)
    doc.close()

    existing  = books[book_id].get("pages", [])
    new_pages = []
    for i in range(num_pages):
        if i < len(existing):
            new_pages.append(existing[i])
        else:
            new_pages.append({"content": [], "type": "words", "teacher_note": ""})

    books[book_id]["num_pages"] = num_pages
    books[book_id]["pages"]     = new_pages
    save_books(books)
    return jsonify({"num_pages": num_pages, "success": True})

@app.route("/admin/book/<book_id>/upload-csv", methods=["POST"])
@admin_required
def admin_upload_csv(book_id):
    """
    CSV columns: page, spanish, english  (page is 1-based)
    Accepts Excel exports (UTF-8 BOM handled).
    """
    books = load_books()
    if book_id not in books:
        return jsonify({"error": "Book not found"}), 404
    if "csv" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    raw    = request.files["csv"].read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))

    page_data = {}
    for row in reader:
        norm = {k.strip().lower(): v.strip() for k, v in row.items() if k}
        try:
            page_idx = int(norm.get("page", 0)) - 1
        except ValueError:
            continue
        es = norm.get("spanish", norm.get("español", norm.get("es", ""))).strip()
        en = norm.get("english", norm.get("inglés", norm.get("en", ""))).strip()
        if not es and not en:
            continue
        page_data.setdefault(page_idx, []).append({"es": es, "en": en})

    pages     = books[book_id].get("pages", [])
    num_pages = books[book_id].get("num_pages", 0)
    while len(pages) < num_pages:
        pages.append({"content": [], "type": "words", "teacher_note": ""})

    for page_idx, items in page_data.items():
        if 0 <= page_idx < num_pages:
            pages[page_idx]["content"] = items

    books[book_id]["pages"] = pages
    save_books(books)
    return jsonify({"success": True, "pages_filled": len(page_data)})

@app.route("/admin/book/<book_id>/save-page", methods=["POST"])
@admin_required
def admin_save_page(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify({"error": "Book not found"}), 404

    data         = request.get_json()
    page_num     = int(data.get("page_num", 0))
    content      = data.get("content", [])
    content_type = data.get("type", "words")
    teacher_note = data.get("teacher_note", "").strip()

    pages = books[book_id].get("pages", [])
    while len(pages) <= page_num:
        pages.append({"content": [], "type": "words", "teacher_note": ""})

    pages[page_num] = {
        "content":      content,
        "type":         content_type,
        "teacher_note": teacher_note
    }
    books[book_id]["pages"] = pages
    save_books(books)
    return jsonify({"success": True})

@app.route("/admin/book/<book_id>/delete", methods=["POST"])
@admin_required
def admin_delete_book(book_id):
    books = load_books()
    books.pop(book_id, None)
    save_books(books)
    return redirect(url_for("admin_dashboard"))

@app.route("/")
def index():
    return redirect(url_for("admin_login"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
