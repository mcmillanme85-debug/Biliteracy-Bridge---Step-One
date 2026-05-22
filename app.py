from flask import (Flask, render_template, request, session,
                   redirect, url_for, jsonify, send_file, make_response)
import json, os, random, io, csv
from pathlib import Path
import fitz        # PyMuPDF
from PIL import Image
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'biliteracy-dev-2025')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024   # 100 MB — handles large PDFs

ADMIN_PASSWORD  = os.environ.get('ADMIN_PASSWORD', 'admin123')
ELEVENLABS_KEY  = os.environ.get('ELEVENLABS_API_KEY', '')
VOICE_ES = "2Lb1en5ujrODDIqmp7F3"   # Jhenny
VOICE_EN = "2EUn20N7uqcXUxqGrJEF"   # Britney

DATA_DIR   = Path("data");        DATA_DIR.mkdir(exist_ok=True)
IMAGES_DIR = Path("page_images"); IMAGES_DIR.mkdir(exist_ok=True)
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

def make_code():
    return str(random.randint(1000, 9999))

def requires_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

def can_view(book_id, book):
    if not book.get("access_code") or book.get("free"):
        return True
    return session.get(f"access_{book_id}") == book.get("access_code")

# ── public ────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("home.html", books=load_books())

@app.route("/book/<book_id>")
def book(book_id):
    books = load_books()
    b = books.get(book_id)
    if not b:
        return "Book not found", 404
    if not can_view(book_id, b):
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
            request.form.get("d1",""), request.form.get("d2",""),
            request.form.get("d3",""), request.form.get("d4",""),
        ]).strip()
        if entered == b.get("access_code",""):
            session[f"access_{book_id}"] = entered
            return redirect(url_for("book", book_id=book_id))
        error = "That code didn't match. Please try again."
    return render_template("access.html", book=b, book_id=book_id, error=error)

@app.route("/page-image/<book_id>/<int:idx>")
def page_image(book_id, idx):
    p = IMAGES_DIR / book_id / f"page_{idx}.jpg"
    if not p.exists():
        return "Not found", 404
    return send_file(p, mimetype="image/jpeg")

@app.route("/speak/<book_id>/<int:idx>/<lang>")
def speak(book_id, idx, lang):
    books = load_books()
    b = books.get(book_id)
    if not b or not can_view(book_id, b):
        return jsonify(error="Access denied"), 403
    pages = b.get("pages", [])
    if idx >= len(pages):
        return jsonify(error="No page"), 404
    word = pages[idx].get("spanish" if lang == "es" else "english", "")
    if not word:
        return jsonify(error="No word"), 400
    if not ELEVENLABS_KEY:
        return jsonify(error="No API key"), 500
    try:
        client = ElevenLabs(api_key=ELEVENLABS_KEY)
        audio_iter = client.text_to_speech.convert(
            text=word,
            voice_id=VOICE_ES if lang == "es" else VOICE_EN,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(stability=0.80, similarity_boost=0.75, style=0.3)
        )
        audio_bytes = b"".join(audio_iter)
        return send_file(io.BytesIO(audio_bytes), mimetype="audio/mpeg")
    except Exception as e:
        print(f"ElevenLabs error: {e}")
        return jsonify(error=str(e)), 500

# ── admin ────────────────────────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET","POST"])
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
    return render_template("admin_dashboard.html", books=load_books())

@app.route("/admin/book/<book_id>")
@requires_admin
def admin_book(book_id):
    books = load_books()
    b = books.get(book_id)
    if not b:
        return "Book not found", 404
    # auto-create a locked code if none exists yet
    if not b.get("access_code"):
        b["access_code"] = make_code()
        b["code_locked"] = True
        books[book_id] = b
        save_books(books)
    msg     = request.args.get("msg", "")
    msg_val = request.args.get("val", "")
    return render_template("admin_book.html",
                           book=b, book_id=book_id,
                           msg=msg, msg_val=msg_val)

@app.route("/admin/new-book", methods=["GET","POST"])
@requires_admin
def admin_new_book():
    if request.method == "POST":
        title   = request.form.get("title","").strip()
        book_id = (request.form.get("book_id","")
                   .strip().lower().replace(" ","-"))
        free    = request.form.get("free") == "on"
        books   = load_books()
        if book_id in books:
            return render_template("admin_new_book.html",
                                   error="That ID already exists.")
        code = "" if free else make_code()
        books[book_id] = {
            "title": title, "num_pages": 0, "pages": [],
            "free": free, "access_code": code,
            "code_locked": bool(code)
        }
        save_books(books)
        (IMAGES_DIR / book_id).mkdir(exist_ok=True)
        return redirect(url_for("admin_book", book_id=book_id))
    return render_template("admin_new_book.html")

# ── PDF upload via standard HTML form POST ─────────────────────────────────

@app.route("/admin/book/<book_id>/upload-pdf", methods=["POST"])
@requires_admin
def upload_pdf(book_id):
    books = load_books()
    if book_id not in books:
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="pdf_err", val="Book not found"))
    f = request.files.get("pdf")
    if not f or not f.filename:
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="pdf_err", val="No file selected"))
    try:
        pdf_bytes = f.read()
        img_dir   = IMAGES_DIR / book_id
        img_dir.mkdir(exist_ok=True)
        for old in img_dir.glob("*.jpg"):
            old.unlink()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        num_pages = len(doc)
        for i, page in enumerate(doc):
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img.save(img_dir / f"page_{i}.jpg", quality=85)
        # Extend pages list
        pages = books[book_id].get("pages", [])
        while len(pages) < num_pages:
            pages.append({"english":"","spanish":"","teacher_note":False,"custom_tip":""})
        books[book_id]["pages"]     = pages
        books[book_id]["num_pages"] = num_pages
        save_books(books)
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="pdf_ok", val=str(num_pages)))
    except Exception as e:
        print(f"PDF upload error: {e}")
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="pdf_err", val=str(e)))

# ── CSV upload via standard HTML form POST ─────────────────────────────────

@app.route("/admin/book/<book_id>/upload-csv", methods=["POST"])
@requires_admin
def upload_csv(book_id):
    books = load_books()
    if book_id not in books:
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="csv_err", val="Book not found"))
    f = request.files.get("csv")
    if not f or not f.filename:
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="csv_err", val="No file selected"))
    try:
        content = f.read().decode("utf-8-sig").splitlines()
        reader  = csv.DictReader(content)
        pages   = books[book_id].get("pages", [])
        filled  = 0
        for row in reader:
            raw_pg = row.get("page") or row.get("Page") or ""
            try:
                idx = int(raw_pg.strip()) - 1
            except ValueError:
                continue
            if 0 <= idx < len(pages):
                en = (row.get("english") or row.get("English") or "").strip()
                es = (row.get("spanish") or row.get("Spanish") or "").strip()
                pages[idx]["english"] = en
                pages[idx]["spanish"] = es
                filled += 1
        books[book_id]["pages"] = pages
        save_books(books)
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="csv_ok", val=str(filled)))
    except Exception as e:
        print(f"CSV upload error: {e}")
        return redirect(url_for("admin_book", book_id=book_id,
                                msg="csv_err", val=str(e)))

# ── Save page words (AJAX — small payload, reliable) ──────────────────────

@app.route("/admin/book/<book_id>/save-page", methods=["POST"])
@requires_admin
def save_page(book_id):
    books = load_books()
    if book_id not in books:
        return jsonify(error="Not found"), 404
    data  = request.get_json()
    idx   = data.get("page_idx", 0)
    pages = books[book_id].get("pages", [])
    while len(pages) <= idx:
        pages.append({"english":"","spanish":"","teacher_note":False,"custom_tip":""})
    pages[idx]["english"]      = data.get("english","")
    pages[idx]["spanish"]      = data.get("spanish","")
    pages[idx]["custom_tip"]   = data.get("custom_tip","")
    pages[idx]["teacher_note"] = data.get("teacher_note", False)
    books[book_id]["pages"] = pages
    save_books(books)
    return jsonify(success=True)

if __name__ == "__main__":
    app.run(debug=True)
