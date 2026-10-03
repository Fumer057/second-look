"""Second Look - a scam checker built for my parent, powered by Gemma (open weights).

Works with ANY OpenAI-compatible endpoint:
  * Google AI Studio (hosted Gemma)  -> LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
  * Ollama on your own laptop        -> LLM_BASE_URL=http://localhost:11434/v1   (LLM_MODEL=gemma3:4b)
  * OpenRouter / vLLM / llama.cpp    -> whatever their /v1 URL is
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
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
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 4000

BASE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Optional MongoDB Atlas: stores ONLY anonymized verdicts (never the message).
# ---------------------------------------------------------------------------
checks_col = None
if MONGODB_URI:
    try:
        from pymongo import MongoClient

        checks_col = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=4000)["second_look"]["checks"]
        log.info("MongoDB history enabled")
    except Exception as exc:  # noqa: BLE001
        log.warning("MongoDB disabled: %s", exc)

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

Reply with ONLY a JSON object, no markdown, in exactly this shape:
{{
  "verdict": "scam" | "suspicious" | "safe",
  "confidence": "high" | "medium" | "low",
  "headline": "one short sentence they can understand instantly",
  "red_flags": ["short reason 1", "short reason 2"],
  "what_to_do": ["simple step 1", "simple step 2"],
  "note_for_family": "one or two sentences summarising this for their son or daughter"
}}

The message to check:
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
    if verdict not in {"scam", "suspicious", "safe"}:
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
                last_error = f"{model}: {exc}"
                continue
            if resp.status_code in (400, 404) and len(LLM_MODELS) > 1:
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


app = FastAPI(title="Second Look")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
async def health():
    return {"ok": True, "models": LLM_MODELS, "base_url": LLM_BASE_URL, "history": checks_col is not None}


@app.post("/api/check")
async def check(
    text: str = Form(""),
    language: str = Form("English"),
    image: UploadFile | None = File(None),
):
    text = redact(text.strip())[:MAX_TEXT_CHARS]
    image_bytes = await image.read() if image is not None else b""
    if not text and not image_bytes:
        raise HTTPException(status_code=400, detail="Please paste a message or add a screenshot.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Screenshot is too big (max 5 MB).")

    language = re.sub(r"[^\w\s()-]", "", language)[:40] or "English"
    message = text or "(see the attached screenshot - read all text in it carefully)"
    content: list[dict] = [
        {"type": "text", "text": PROMPT.format(region=REGION, language=language, message=message)}
    ]
    if image_bytes:
        mime = image.content_type if image and image.content_type else "image/png"
        if not mime.startswith("image/"):
            raise HTTPException(status_code=400, detail="That file is not an image.")
        b64 = base64.b64encode(image_bytes).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    result, model = await ask_gemma(content)
    result["model"] = model

    if checks_col is not None:
        try:
            checks_col.insert_one(
                {
                    "at": datetime.now(timezone.utc),
                    "verdict": result["verdict"],
                    "headline": result["headline"],
                    "red_flags": result["red_flags"],
                    "language": language,
                    "had_image": bool(image_bytes),
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not save history: %s", exc)

    return JSONResponse(result)


@app.get("/api/history")
async def history():
    if checks_col is None:
        return {"enabled": False, "items": []}
    items = list(checks_col.find({}, {"_id": 0}).sort("at", -1).limit(20))
    for item in items:
        item["at"] = item["at"].isoformat()
    return {"enabled": True, "items": items}
