"""Second Look - a scam checker built for my parent, powered by Gemma (open weights).

Two front doors, one brain:
  * Web app  (/ quick check, /chat WhatsApp-style chat)
  * WhatsApp (/whatsapp webhook via Twilio) - just forward the suspicious message

Works with ANY OpenAI-compatible endpoint:
  * Google AI Studio (hosted Gemma)  -> LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
  * Ollama on your own laptop        -> LLM_BASE_URL=http://localhost:11434/v1   (LLM_MODEL=gemma3:4b)
  * OpenRouter / vLLM / llama.cpp    -> whatever their /v1 URL is
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv()
log = logging.getLogger("second-look")
logging.basicConfig(level=logging.INFO)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# Comma-separated list: first model that works wins (handy when model IDs change).
LLM_MODELS = [m.strip() for m in os.getenv("LLM_MODEL", "gemma-4-26b-a4b-it,gemma-4-31b-it").split(",") if m.strip()]
REGION = os.getenv("REGION", "India")
MONGODB_URI = os.getenv("MONGODB_URI", "")

# WhatsApp via Twilio (sandbox or a real sender)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # Twilio sandbox number
WHATSAPP_JOIN_CODE = os.getenv("WHATSAPP_JOIN_CODE", "")  # e.g. "join happy-tiger" (sandbox only)
TWILIO_VALIDATE = os.getenv("TWILIO_VALIDATE", "true").lower() != "false"
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 4000
BASE_DIR = Path(__file__).parent

LANGUAGES = {
    "english": "English", "hindi": "Hindi", "हिंदी": "Hindi", "हिन्दी": "Hindi",
    "bengali": "Bengali", "bangla": "Bengali", "বাংলা": "Bengali",
    "marathi": "Marathi", "मराठी": "Marathi", "tamil": "Tamil", "தமிழ்": "Tamil",
    "telugu": "Telugu", "తెలుగు": "Telugu", "kannada": "Kannada", "ಕನ್ನಡ": "Kannada",
    "malayalam": "Malayalam", "മലയാളം": "Malayalam", "gujarati": "Gujarati", "ગુજરાતી": "Gujarati",
    "punjabi": "Punjabi", "ਪੰਜਾਬੀ": "Punjabi", "urdu": "Urdu", "اردو": "Urdu",
    "spanish": "Spanish", "español": "Spanish",
}

# ---------------------------------------------------------------------------
# Optional MongoDB Atlas: anonymized verdicts + hashed-phone language prefs.
# Never stores the message itself.
# ---------------------------------------------------------------------------
checks_col = prefs_col = None
if MONGODB_URI:
    try:
        from pymongo import MongoClient

        _db = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=4000)["second_look"]
        checks_col, prefs_col = _db["checks"], _db["prefs"]
        log.info("MongoDB enabled")
    except Exception as exc:  # noqa: BLE001
        log.warning("MongoDB disabled: %s", exc)

# ---------------------------------------------------------------------------
# Short-term conversation memory so follow-ups ("I already clicked it!") work.
# Keyed by web session id or hashed phone number. Bounded, in-memory.
# ---------------------------------------------------------------------------
SESSIONS: OrderedDict[str, dict] = OrderedDict()
MAX_SESSIONS = 2000


def session_get(key: str) -> dict:
    s = SESSIONS.pop(key, None) or {}
    SESSIONS[key] = s
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)
    return s


def hash_id(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Privacy: scrub card / Aadhaar / long account numbers before they leave us.
# Phone numbers and links are kept on purpose - they are scam signals.
# ---------------------------------------------------------------------------
_REDACTIONS = [
    (re.compile(r"\b(?:\d[ -]?){15,18}\d\b"), "[CARD/ACCOUNT NUMBER]"),
    (re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b"), "[ID NUMBER]"),
    (re.compile(r"\b\d{11,14}\b"), "[ACCOUNT NUMBER]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
]


def redact(text: str) -> str:
    for pattern, label in _REDACTIONS:
        text = pattern.sub(label, text)
    return text


PROMPT = """You are "Second Look", a calm, kind helper for an older parent who is not good with technology.
They received a message (SMS, WhatsApp, email, call notes or a screenshot) and want to know if it is a scam.
The person lives in {region}.

Common scams to watch for: fake KYC/bank account blocked, electricity bill disconnection, UPI "collect"
requests or "enter PIN to RECEIVE money", OTP requests, courier/customs parcels, "digital arrest" by fake
police/CBI/customs, fake relative or friend urgently needing money, lottery/prize/refund, part-time job or
"like videos" task scams, investment/trading groups, links to install APK files or remote apps
(AnyDesk, TeamViewer, QuickSupport), fake customer care numbers, impersonated government schemes.

Rules:
- Real banks and government never ask for OTP, PIN, CVV or passwords. Receiving money NEVER needs a PIN.
- Urgency, threats, secrecy, strange links, unknown numbers and spelling errors are red flags.
- Never say something is 100% safe. If it looks safe, still say how to double-check.
- Use very simple words, short sentences, no jargon. Be reassuring, never make them feel stupid.
- If it is a scam and they may have already clicked, paid or shared an OTP, tell them exactly what to do
  right now (call their bank, block the card/UPI). In India, mention calling 1930 or cybercrime.gov.in.
- Write every text value in {language}. Keep JSON keys and the verdict value in English.

Conversation so far (may be empty):
{context}

If the new input is NOT a message to check but the person talking to you (a question, a worry, or a
follow-up like "I already clicked it" or "what is 1930?"), use verdict "info": answer them directly in
"headline", put any steps in "what_to_do", and leave "red_flags" empty. Use the conversation above.

Reply with ONLY a JSON object, no markdown, in exactly this shape:
{{
  "verdict": "scam" | "suspicious" | "safe" | "info",
  "confidence": "high" | "medium" | "low",
  "headline": "one short sentence they can understand instantly",
  "red_flags": ["short reason 1", "short reason 2"],
  "what_to_do": ["simple step 1", "simple step 2"],
  "note_for_family": "one or two sentences summarising this for their son or daughter"
}}

The new input:
\"\"\"
{message}
\"\"\"
"""


def extract_json(raw: str) -> dict:
    # Gemma 4 "thinks" first and returns <thought>...</thought> inside the content.
    raw = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(raw[start : end + 1])


def normalize(data: dict) -> dict:
    verdict = str(data.get("verdict", "suspicious")).lower().strip()
    if verdict not in {"scam", "suspicious", "safe", "info"}:
        verdict = "suspicious"

    def as_list(v):
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x) for x in (v or []) if str(x).strip()][:6]

    return {
        "verdict": verdict,
        "confidence": str(data.get("confidence", "medium")).lower(),
        "headline": str(data.get("headline", "")).strip(),
        "red_flags": as_list(data.get("red_flags")),
        "what_to_do": as_list(data.get("what_to_do")),
        "note_for_family": str(data.get("note_for_family", "")).strip(),
    }


async def ask_gemma(content: list[dict]) -> tuple[dict, str]:
    """Call the OpenAI-compatible endpoint, trying each configured model in turn."""
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    last_error = "no model configured"
    async with httpx.AsyncClient(timeout=90) as client:
        for model in LLM_MODELS:
            # Note: no "system" role - Gemma's chat template has no system turn, so
            # instructions live in the user message (works on every provider).
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2,
                "max_tokens": 4096,
            }
            try:
                resp = await client.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{model}: {exc!r}"
                continue
            if resp.status_code in (400, 404, 429, 500, 503) and len(LLM_MODELS) > 1:
                last_error = f"{model}: HTTP {resp.status_code} {resp.text[:200]}"
                log.warning("Model failed, trying next: %s", last_error)
                continue
            if resp.status_code != 200:
                last_error = f"{model}: HTTP {resp.status_code} {resp.text[:300]}"
                break
            text = resp.json()["choices"][0]["message"]["content"] or ""
            try:
                return normalize(extract_json(text)), model
            except (ValueError, json.JSONDecodeError):
                last_error = f"{model}: could not parse model reply"
                log.warning("Unparseable reply: %s", text[:300])
                continue
    log.error("All models failed: %s", last_error)
    raise HTTPException(status_code=502, detail="The checker is busy right now.")


def context_text(session: dict) -> str:
    turns = session.get("turns", [])[-3:]
    return "\n".join(f"- They sent: {t['input']}\n  You said ({t['verdict']}): {t['headline']}" for t in turns) or "(none)"


async def run_check(
    text: str,
    image_bytes: bytes,
    mime: str,
    language: str,
    session_key: str | None,
    source: str,
) -> dict:
    """The one brain behind the web app, the web chat and WhatsApp."""
    text = redact(text.strip())[:MAX_TEXT_CHARS]
    session = session_get(session_key) if session_key else {}
    message = text or "(see the attached screenshot - read all text in it carefully)"
    content: list[dict] = [
        {
            "type": "text",
            "text": PROMPT.format(region=REGION, language=language, context=context_text(session), message=message),
        }
    ]
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    result, model = await ask_gemma(content)
    result["model"] = model

    if session_key is not None:
        turns = session.setdefault("turns", [])
        turns.append({"input": (text or "[screenshot]")[:300], "verdict": result["verdict"], "headline": result["headline"]})
        del turns[:-5]

    if checks_col is not None and result["verdict"] != "info":
        try:
            checks_col.insert_one(
                {
                    "at": datetime.now(timezone.utc),
                    "verdict": result["verdict"],
                    "headline": result["headline"],
                    "red_flags": result["red_flags"],
                    "language": language,
                    "had_image": bool(image_bytes),
                    "source": source,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not save history: %s", exc)
    return result


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------
app = FastAPI(title="Second Look")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def whatsapp_link() -> str:
    if not TWILIO_ACCOUNT_SID:
        return ""
    number = re.sub(r"\D", "", TWILIO_WHATSAPP_FROM)
    text = WHATSAPP_JOIN_CODE or "hi"
    return f"https://wa.me/{number}?text={quote(text)}"


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/chat")
async def chat_page():
    return FileResponse(BASE_DIR / "static" / "chat.html")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "models": LLM_MODELS,
        "history": checks_col is not None,
        "whatsapp": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
    }


@app.get("/api/config")
async def config():
    return {"whatsapp_link": whatsapp_link(), "whatsapp_join": WHATSAPP_JOIN_CODE}


def clean_language(language: str) -> str:
    return re.sub(r"[^\w\s()-]", "", language)[:40] or "English"


@app.post("/api/check")
async def check(
    text: str = Form(""),
    language: str = Form("English"),
    session_id: str = Form(""),
    image: UploadFile | None = File(None),
):
    image_bytes = await image.read() if image is not None else b""
    if not text.strip() and not image_bytes:
        raise HTTPException(status_code=400, detail="Please paste a message or add a screenshot.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Screenshot is too big (max 5 MB).")
    mime = (image.content_type if image is not None else "") or "image/png"
    if image_bytes and not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="That file is not an image.")

    key = f"web:{session_id[:64]}" if session_id else None
    result = await run_check(text, image_bytes, mime, clean_language(language), key, "web")
    return JSONResponse(result)


@app.get("/api/history")
async def history():
    if checks_col is None:
        return {"enabled": False, "items": []}
    items = list(checks_col.find({}, {"_id": 0}).sort("at", -1).limit(20))
    for item in items:
        item["at"] = item["at"].isoformat()
    return {"enabled": True, "items": items}


# ---------------------------------------------------------------------------
# WhatsApp (Twilio)
# ---------------------------------------------------------------------------
VERDICT_LABEL = {
    "scam": "🚨 *SCAM. Do not reply*",
    "suspicious": "⚠️ *BE CAREFUL*",
    "safe": "✅ *Looks OK*",
    "info": "💬",
}

LANG_NAMES = sorted(set(LANGUAGES.values()))


def welcome_text(language: str) -> str:
    return (
        "🛡️ *Second Look*\n"
        "Got a strange message? *Forward it to me* (or send a screenshot) and I'll tell you if it's a scam.\n\n"
        f"🌐 I reply in: *{language}*\n"
        "To change, send: *language Hindi* (or " + ", ".join(n for n in LANG_NAMES if n != "Hindi") + ")\n\n"
        "🔒 Never share your OTP, PIN or password with anyone. Not even me."
    )


def format_whatsapp(r: dict) -> str:
    parts = [f"{VERDICT_LABEL[r['verdict']]}\n{r['headline']}".strip()]
    if r["red_flags"]:
        parts.append("*Why:*\n" + "\n".join(f"• {x}" for x in r["red_flags"]))
    if r["what_to_do"]:
        parts.append("*What to do:*\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(r["what_to_do"], 1)))
    if r["verdict"] in ("scam", "suspicious"):
        parts.append("_Already clicked or paid? Just tell me and I'll help._")
    parts.append("_Checked by Gemma, an open model_")
    return "\n\n".join(parts)[:1590]


def twiml(message: str | None) -> Response:
    body = f"<Message>{xml_escape(message)}</Message>" if message else ""
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="application/xml")


def twilio_signature_ok(request: Request, params: dict) -> bool:
    if not (TWILIO_VALIDATE and TWILIO_AUTH_TOKEN):
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    if PUBLIC_URL:
        url = PUBLIC_URL + request.url.path
    else:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        url = f"{proto}://{request.headers.get('host', request.url.netloc)}{request.url.path}"
    payload = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(TWILIO_AUTH_TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


async def send_whatsapp(to: str, body: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={"From": TWILIO_WHATSAPP_FROM, "To": to, "Body": body},
        )
    if resp.status_code >= 300:
        log.error("Twilio send failed: %s %s", resp.status_code, resp.text[:300])


def get_language(user_key: str) -> str:
    s = session_get(user_key)
    if "lang" not in s and prefs_col is not None:
        try:
            doc = prefs_col.find_one({"_id": user_key})
            if doc:
                s["lang"] = doc["lang"]
        except Exception:  # noqa: BLE001
            pass
    return s.get("lang", "English")


def set_language(user_key: str, language: str) -> None:
    session_get(user_key)["lang"] = language
    if prefs_col is not None:
        try:
            prefs_col.update_one({"_id": user_key}, {"$set": {"lang": language}}, upsert=True)
        except Exception:  # noqa: BLE001
            pass


async def process_whatsapp(to: str, user_key: str, text: str, media_url: str, media_type: str) -> None:
    """Runs after we've already acked Twilio (its webhook times out after 15s)."""
    language = get_language(user_key)
    try:
        image_bytes = b""
        if media_url:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                media = await client.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
                media.raise_for_status()
                image_bytes = media.content[:MAX_IMAGE_BYTES]
        result = await run_check(text, image_bytes, media_type or "image/jpeg", language, user_key, "whatsapp")
        await send_whatsapp(to, format_whatsapp(result))
    except Exception as exc:  # noqa: BLE001
        log.exception("WhatsApp processing failed: %s", exc)
        await send_whatsapp(to, "😟 Sorry, I couldn't check that right now. Please try again in a minute.\n\n"
                                "Until then: don't click links, don't share OTP/PIN, don't pay anyone.")


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request, background: BackgroundTasks):
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    if not twilio_signature_ok(request, params):
        log.warning("Rejected WhatsApp webhook: bad Twilio signature (check PUBLIC_URL / TWILIO_AUTH_TOKEN)")
        return Response(status_code=403)

    sender = params.get("From", "")
    text = params.get("Body", "").strip()
    num_media = int(params.get("NumMedia", "0") or 0)
    media_url = params.get("MediaUrl0", "") if num_media else ""
    media_type = params.get("MediaContentType0", "") if num_media else ""
    user_key = f"wa:{hash_id(sender)}"
    lowered = text.lower()

    if media_url and not media_type.startswith("image/"):
        return twiml("I can read text messages and screenshots (images). Please send the message as text or a screenshot. 🙏")

    # Commands that don't need the model: instant replies.
    if not media_url:
        if lowered in {"hi", "hello", "hey", "help", "start", "menu", "namaste", "नमस्ते", "?"} or not text:
            return twiml(welcome_text(get_language(user_key)))
        m = re.match(r"^(?:language|lang|bhasha|भाषा)\s*[:\-]?\s*(\S+)", text, flags=re.IGNORECASE)
        if m:
            lang = LANGUAGES.get(m.group(1).lower())
            if not lang:
                return twiml("I don't know that language yet. Try: " + ", ".join(LANG_NAMES))
            set_language(user_key, lang)
            return twiml(f"✅ OK! I'll reply in *{lang}* from now on. Forward me any message to check.")

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        return twiml("Second Look is not fully set up yet (missing Twilio credentials).")

    background.add_task(process_whatsapp, sender, user_key, text, media_url, media_type)
    return twiml("🔍 Checking carefully… I'll reply in about 30 seconds.\nDon't click anything in that message meanwhile.")
