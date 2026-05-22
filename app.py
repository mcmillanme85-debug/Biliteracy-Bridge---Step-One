from flask import Flask, render_template, request, session, redirect, url_for, jsonify, send_file, make_response
import json, os, random, io, base64, csv
from pathlib import Path
import fitz  # PyMuPDF
from PIL import Image
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'biliteracy-dev-key-2025')

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
VOICE_ES = "2Lb1en5ujrODDIqmp7F3"   # Jhenny (Spanish)
VOICE_EN = "2EUn20N7uqcXUxqGrJEF"   # Britney (English)

DATA_DIR = Path("data")
UPLOADS_DIR = Path("uploads")
IMAGES_DIR = Path("page_images")
for d in [DATA_DIR, UPLOADS_DIR, IMAGES_DIR]:
    d.mkdir(exist_ok=True)

BOOKS_FILE = DATA_DIR / "books.json"

# ── helpers ──────────────────────────────────────────────────────────────────

def load_books():
    if BOOKS_FILE.exists():
        with open(BOOKS_FILE) as f:
            return json.load(f)
    return {}

def save_books(books):
    with open(BOOKS_FILE, "w") as f:
        json.dump(books, f, indent=2)

def generate_code():
    """Return a memorable 4-digit numeric code (1000–9999)."""
    return str(random.randint(1000, 9999))

def requires_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

def book_accessible(book_id, book):
    """True if the user can view this book (no code, or code entered)."""
    if not book.get("access_code"):          # no code set = always open
        return True
    if book.get("free", False):              # flagged free
        return True
    entered = session.get(f"access_{book_id}")
    return entered == book.get("access_code")

# ── public routes ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    books = load_books()
    return render_template("home.html", books=books)

@app.route("/book/<book_id>")
def book(book_id):
    books = load_books()
    b = books.get(book_id)
    if not b:
        return "Book not found", 404
    if not book_accessible(book_id, b):
        return redirect(url_for("access", book_id=book_id))
    return render_template("book.html", book=b, book_id=book_id)

@app.route("/access/<book_id>", methods=["GET", "POST"])
def access(book_id):
    books = load_books()
    b = books.get(book_id)
    if not b:
        return "Book not found", 404
    error = None
    if request.method == "POST":
        entered = "".join([
            request.form.get("d1", ""),
            request.form.get("d2", ""),
            request.form.get("d3", ""),
            request.form.get("d4", ""),
        ]).strip()
        if entered == b.get("access_code", ""):
            session[f"access_{book_id}"] = entered
            return redirect(url_for("book", book_id=book_id))
        else:
            error = "That code didn't match. Please try again."
    return render_template("access.html", book=b, book_id=book_id, error=error)

@app.route("/page-image/<book_id>/<int:page_idx>")
def page_image(book_id, page_idx):
    img_path = IMAGES_DIR / book_id / f"page_{page_idx}.jpg"
    if not img_path.exists():
        return "Image not found", 404
    return send_file(img_path, mimetype="image/jpeg")

@app.route("/speak/<book_id>/<int:page_idx>/<lang>")
def speak(book_id, page_idx, lang):
    books = load_books()
    b = books.get(book_id)
    if not b:
        return jsonify(error="Book not found"), 404
    if not book_accessible(book_id, b):
        return jsonify(error="Access required"), 403
    pages = b.get("pages", [])
    if page_idx >= len(pages):
        return jsonify(error="Page not found"), 404
    page = pages[page_idx]
    word = page.get("spanish" if lang == "es" else "english", "")
    if not word:
        return jsonify(error="No word on this page"), 400
    if not ELEVENLABS_API_KEY:
        return jsonify(error="ElevenLabs key not configured"), 500
    try:
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        voice_id = VOICE_ES if lang == "es" else VOICE_EN
        audio = client.text_to_speech.convert(
            text=word,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(stability=0.80, similarity_boost=0.75, style=0.3)
        )
        audio_bytes = b"".join(audio)
        return send_file(io.BytesIO(audio_bytes), mimetype="audio/mpeg")
    except Exception as e:
        return jsonify(error=str(e)), 500

# ── admin routes ──────────────────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Incorrect password."
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("home"))

@app.route("/admin")
@requires_admin
def admin_dashboard():
    books = load_books()
    return render_template("admin_dashboard.html", books=books)

@app.route("/admin/new-book", methods=["GET", "POST"])
@requires_admin
def admin_new_book():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        book_id = request.form.get("book_id", "").strip().lower().replace(" ", "-")
        free = request.form.get("free") == "on"
        books = load_books()
        if book_id in books:
            return render_template("admin_new_book.html", error="That ID already exists.")
        books[book_id] = {
            "title": title,
            "num_pages": 0,
            "pages": [],
            "free": free,
            "access_code": "" if free else generate_code()
        }
        save_books(books)
        (IMAGES_DIR / book_id).mkdir(exist_ok=True)
        return redirect(url_for("admin_book", book_id=book_id))
    return render_template("admin_new_book.html")

@app.route("/admin/book/<book_id>")
@requires_admin
def admin_book(book_id):
    books = load_books()
    b = books.get(book_id)
    if not b:
        return "Book not found", 404
    return render_template("admin_book.html", book=b, book_id=book_id)

@app.route("/admin/book/<book_id>/generate-code", methods=["POST"])
@requires_admin
def admin_generate_code(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify(error="Not found"), 404
    code = generate_code()
    books[book_id]["access_code"] = code
    save_books(books)
    return jsonify(code=code)

@app.route("/admin/book/<book_id>/toggle-free", methods=["POST"])
@requires_admin
def admin_toggle_free(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify(error="Not found"), 404
    books[book_id]["free"] = not books[book_id].get("free", False)
    save_books(books)
    return jsonify(free=books[book_id]["free"])

@app.route("/admin/book/<book_id>/upload-pdf", methods=["POST"])
@requires_admin
def upload_pdf(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify(error="Book not found"), 404
    f = request.files.get("pdf")
    if not f:
        return jsonify(error="No file"), 400
    pdf_bytes = f.read()
    img_dir = IMAGES_DIR / book_id
    img_dir.mkdir(exist_ok=True)
    # Clear old images
    for old in img_dir.glob("*.jpg"):
        old.unlink()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    num_pages = len(doc)
    for i, page in enumerate(doc):
        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.save(img_dir / f"page_{i}.jpg", quality=85)
    # Extend pages array if needed
    while len(books[book_id]["pages"]) < num_pages:
        books[book_id]["pages"].append({"english": "", "spanish": "", "teacher_note": False})
    books[book_id]["num_pages"] = num_pages
    save_books(books)
    return jsonify(success=True, num_pages=num_pages)

@app.route("/admin/book/<book_id>/save-page", methods=["POST"])
@requires_admin
def save_page(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify(error="Not found"), 404
    data = request.get_json()
    page_idx = data.get("page_idx")
    pages = books[book_id]["pages"]
    while len(pages) <= page_idx:
        pages.append({"english": "", "spanish": "", "teacher_note": False})
    pages[page_idx]["english"] = data.get("english", "")
    pages[page_idx]["spanish"] = data.get("spanish", "")
    pages[page_idx]["teacher_note"] = data.get("teacher_note", False)
    save_books(books)
    return jsonify(success=True)

@app.route("/admin/book/<book_id>/upload-csv", methods=["POST"])
@requires_admin
def upload_csv(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify(error="Not found"), 404
    f = request.files.get("csv")
    if not f:
        return jsonify(error="No file"), 400
    content = f.read().decode("utf-8").splitlines()
    reader = csv.DictReader(content)
    pages = books[book_id]["pages"]
    filled = 0
    for row in reader:
        try:
            idx = int(row.get("page", row.get("Page", ""))) - 1
            if 0 <= idx < len(pages):
                pages[idx]["english"] = row.get("english", row.get("English", "")).strip()
                pages[idx]["spanish"] = row.get("spanish", row.get("Spanish", "")).strip()
                filled += 1
        except (ValueError, TypeError):
            continue
    save_books(books)
    return jsonify(success=True, pages_filled=filled)

if __name__ == "__main__":
    app.run(debug=True)
