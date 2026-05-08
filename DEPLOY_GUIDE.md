# 🚀 Deploy Your Digital Dictionary — Step-by-Step Guide
## Render.com (free) + Hostinger Domain

---

## WHAT YOU'LL NEED
- A GitHub account (free) → github.com
- A Render.com account (free) → render.com
- Your Hostinger login
- Your ElevenLabs API key → elevenlabs.io

---

## PART 1 — UPLOAD YOUR CODE TO GITHUB
*(GitHub stores your code so Render can read it)*

**Step 1.** Go to github.com and sign in (or create a free account)

**Step 2.** Click the green **"New"** button (top left)

**Step 3.** Fill in:
- Repository name: `digital-dictionary`
- Set to **Private**
- Click **"Create repository"**

**Step 4.** On the next screen, click **"uploading an existing file"**

**Step 5.** Drag and drop ALL these files into the window:
```
app.py
requirements.txt
Procfile
render.yaml
templates/
  └── index.html
```
> ⚠️ Make sure `index.html` is INSIDE a folder called `templates`

**Step 6.** Click **"Commit changes"** (green button at the bottom)

✅ Your code is now on GitHub!

---

## PART 2 — DEPLOY ON RENDER.COM (FREE)

**Step 7.** Go to render.com and sign in with your GitHub account

**Step 8.** Click **"New +"** → select **"Web Service"**

**Step 9.** Click **"Connect a repository"** → find `digital-dictionary` → click **Connect**

**Step 10.** Fill in these settings:
| Field | Value |
|---|---|
| Name | `digital-dictionary` |
| Region | Oregon (US West) |
| Branch | `main` |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt && apt-get install -y poppler-utils` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |

**Step 11.** Scroll down to **"Environment Variables"** → click **"Add Environment Variable"**:
| Key | Value |
|---|---|
| `SECRET_KEY` | (type any random string, e.g. `my-dictionary-secret-2024`) |

**Step 12.** Make sure the plan shows **"Free"** at the bottom

**Step 13.** Click **"Create Web Service"**

⏳ Wait 3–5 minutes while Render builds your app.
You'll see logs scrolling — wait until you see **"Your service is live"**

**Step 14.** Copy your Render URL — it looks like:
```
https://digital-dictionary-xxxx.onrender.com
```
Test it in your browser — you should see your dictionary app! ✅

---

## PART 3 — CONNECT YOUR HOSTINGER DOMAIN

*(So your app shows at e.g. `dictionary.yourdomain.com`)*

### In Render.com:

**Step 15.** In your Render dashboard → click your service → go to **"Settings"**

**Step 16.** Scroll to **"Custom Domains"** → click **"Add Custom Domain"**

**Step 17.** Type in a subdomain for your site, e.g.:
```
dictionary.yourdomain.com
```
*(Replace `yourdomain.com` with your actual Hostinger domain)*

**Step 18.** Render will show you a **CNAME record** that looks like:
```
Type:  CNAME
Name:  dictionary
Value: digital-dictionary-xxxx.onrender.com
```
**Copy these values — you need them for the next step.**

---

### In Hostinger hPanel:

**Step 19.** Log in to hPanel → click **"Domains"** → click your domain

**Step 20.** Click **"DNS / Nameservers"** → then **"DNS Records"**

**Step 21.** Click **"Add Record"** and fill in:
| Field | Value |
|---|---|
| Type | CNAME |
| Name | `dictionary` |
| Points to | `digital-dictionary-xxxx.onrender.com` |
| TTL | 3600 |

**Step 22.** Click **Save**

⏳ Wait 5–30 minutes for DNS to update (sometimes up to 24 hrs)

**Step 23.** Go back to Render → Custom Domains → you should see a green ✅ checkmark

---

## PART 4 — USE YOUR DICTIONARY

**Step 24.** Visit `https://dictionary.yourdomain.com`

**Step 25.** Get your ElevenLabs API key:
1. Go to elevenlabs.io → sign up free
2. Click your profile → **"API Keys"**
3. Copy the key

**Step 26.** Paste your ElevenLabs key into the **"ElevenLabs Key"** box in the top right of your app

**Step 27.** Click **"Choose PDF File"** and upload your wordbank PDF

**Step 28.** Click any word → hit **"▶ Pronounce"** to hear it in Spanish then English!

---

## ⚠️ FREE TIER NOTES

- **Render free apps "sleep"** after 15 minutes of inactivity — the first visit after sleeping takes ~30 seconds to wake up. This is normal.
- **50 MB max PDF size** (can be increased if needed)
- **No permanent file storage** — uploaded PDFs are temporary. Users re-upload each session.

---

## 🆘 TROUBLESHOOTING

| Problem | Fix |
|---|---|
| App shows "Build failed" | Check logs in Render dashboard for errors |
| "poppler not found" error | Add `apt-get install -y poppler-utils` to Build Command |
| Domain not connecting | Wait 24 hrs for DNS — use Render URL in the meantime |
| No words detected in PDF | PDF may be scanned (image-based) — try a text-based PDF |
| Audio not playing | Double-check your ElevenLabs API key is correct |

---

## NEED HELP?

If you get stuck on any step, share the error message and I can help fix it! 🙌
