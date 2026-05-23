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

# Use /data (Render Persistent Disk) if available, otherwise local fallback
_DISK = Path("/data")
DATA_DIR   = (_DISK / "biliteracy_data")   if _DISK.exists() else Path("data")
IMAGES_DIR = (_DISK / "page_images")       if _DISK.exists() else Path("page_images")
DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
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
    speak_type = request.args.get("type", "word")  # word | sentence | both
    word_idx   = int(request.args.get("word_idx", 0))
    page_data  = pages[idx]
    words_list = page_data.get("words", [])
    if words_list and word_idx < len(words_list):
        word_data = words_list[word_idx]
    else:
        word_data = {"english": page_data.get("english",""), "spanish": page_data.get("spanish",""), "en_sentence":"", "es_sentence":""}
    if lang == "es":
        word      = word_data.get("spanish","")
        sentence  = word_data.get("es_sentence","")
    else:
        word      = word_data.get("english","")
        sentence  = word_data.get("en_sentence","")
    if speak_type == "sentence":
        text = sentence or word
    elif speak_type == "both":
        text = f"{word}. {sentence}" if sentence else word
    else:
        text = word
    if not text:
        return jsonify(error="No text"), 400
    word = text  # reuse variable for the API call below
    if not ELEVENLABS_KEY:
        return jsonify(error="No API key"), 500
    try:
        cfg = load_config()
        voice_id = cfg.get("voice_es_id", VOICE_ES) if lang == "es" else cfg.get("voice_en_id", VOICE_EN)
        client = ElevenLabs(api_key=ELEVENLABS_KEY)
        audio_iter = client.text_to_speech.convert(
            text=word,
            voice_id=voice_id,
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
            pages.append({"words":[{"english":"","spanish":"","en_sentence":"","es_sentence":""}],"teacher_note":False,"custom_tip":""})
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
        # Group rows by page, then word_num
        page_words = {}
        for row in reader:
            raw_pg = row.get("page") or row.get("Page") or ""
            try:
                idx = int(str(raw_pg).strip()) - 1
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(pages):
                try:
                    word_num = int(str(row.get("word_num") or "1").strip()) - 1
                except (ValueError, TypeError):
                    word_num = 0
                word = {
                    "english":     str(row.get("english")     or "").strip(),
                    "spanish":     str(row.get("spanish")     or "").strip(),
                    "en_sentence": str(row.get("en_sentence") or "").strip(),
                    "es_sentence": str(row.get("es_sentence") or "").strip(),
                }
                if idx not in page_words:
                    page_words[idx] = {}
                page_words[idx][word_num] = word
        for idx, words_dict in page_words.items():
            ordered = [words_dict[k] for k in sorted(words_dict.keys())]
            # Always update both the words array AND legacy fields
            pages[idx]["words"]   = ordered
            pages[idx]["english"] = ordered[0]["english"] if ordered else ""
            pages[idx]["spanish"] = ordered[0]["spanish"] if ordered else ""
            if ordered and (ordered[0]["english"] or ordered[0]["spanish"]):
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
        pages.append({"words":[{"english":"","spanish":"","en_sentence":"","es_sentence":""}],"teacher_note":False,"custom_tip":""})
    # Support both legacy single-word and new multi-word structure
    words = data.get("words", None)
    if words is not None:
        pages[idx]["words"] = words
        if words:
            pages[idx]["english"] = words[0].get("english","")
            pages[idx]["spanish"] = words[0].get("spanish","")
    else:
        # Legacy save
        pages[idx]["english"] = data.get("english","")
        pages[idx]["spanish"] = data.get("spanish","")
        en_sentence = data.get("en_sentence","")
        es_sentence = data.get("es_sentence","")
        if "words" not in pages[idx] or not pages[idx]["words"]:
            pages[idx]["words"] = [{"english":pages[idx]["english"],"spanish":pages[idx]["spanish"],"en_sentence":en_sentence,"es_sentence":es_sentence}]
        else:
            pages[idx]["words"][0]["english"]     = pages[idx]["english"]
            pages[idx]["words"][0]["spanish"]      = pages[idx]["spanish"]
            pages[idx]["words"][0]["en_sentence"]  = en_sentence
            pages[idx]["words"][0]["es_sentence"]  = es_sentence
    pages[idx]["custom_tip"]   = data.get("custom_tip","")
    pages[idx]["teacher_note"] = data.get("teacher_note", False)
    books[book_id]["pages"] = pages
    save_books(books)
    return jsonify(success=True)

if __name__ == "__main__":
    app.run(debug=True)

# ── Voice config ──────────────────────────────────────────────────────────────

CONFIG_FILE = DATA_DIR / "config.json"  # lives on persistent disk

def load_config():
    # Env vars take priority (set in Render dashboard for extra safety)
    cfg = {
        "voice_en_id":   os.environ.get("ENGLISH_VOICE_ID", os.environ.get("VOICE_EN_ID", "2EUn20N7uqcXUxqGrJEF")),
        "voice_en_name": os.environ.get("VOICE_EN_NAME", "English Voice"),
        "voice_es_id":   os.environ.get("SPANISH_VOICE_ID", os.environ.get("VOICE_ES_ID", "2Lb1en5ujrODDIqmp7F3")),
        "voice_es_name": os.environ.get("VOICE_ES_NAME", "Kate"),
    }
    # Override with saved config if it exists
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

@app.route("/admin/voices")
@requires_admin
def admin_voices():
    cfg = load_config()
    msg = request.args.get("msg","")
    return render_template("admin_voices.html", config=cfg, msg=msg)

@app.route("/admin/voices/list")
@requires_admin
def voices_list():
    if not ELEVENLABS_KEY:
        return jsonify(error="No ElevenLabs API key configured in environment variables.")
    try:
        import urllib.request, ssl
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": ELEVENLABS_KEY}
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        voices = sorted(data.get("voices",[]), key=lambda v: v.get("name",""))
        return jsonify(voices=voices)
    except Exception as e:
        return jsonify(error=str(e))

@app.route("/admin/voices/preview", methods=["POST"])
@requires_admin
def voice_preview():
    if not ELEVENLABS_KEY:
        return jsonify(error="No API key"), 500
    data     = request.get_json()
    voice_id = data.get("voice_id","")
    text     = data.get("text","Hello, elephant! Hola, elefante!")[:200]
    try:
        client = ElevenLabs(api_key=ELEVENLABS_KEY)
        audio_iter = client.text_to_speech.convert(
            text=text, voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(stability=0.75, similarity_boost=0.75)
        )
        return send_file(io.BytesIO(b"".join(audio_iter)), mimetype="audio/mpeg")
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route("/admin/voices/save", methods=["POST"])
@requires_admin
def voices_save():
    data = request.get_json()
    cfg  = load_config()
    cfg["voice_en_id"]   = data.get("voice_en_id",   cfg.get("voice_en_id",""))
    cfg["voice_en_name"] = data.get("voice_en_name", cfg.get("voice_en_name",""))
    cfg["voice_es_id"]   = data.get("voice_es_id",   cfg.get("voice_es_id",""))
    cfg["voice_es_name"] = data.get("voice_es_name", cfg.get("voice_es_name",""))
    save_config(cfg)
    return jsonify(success=True)
