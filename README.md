# 🛡️ Second Look

**A scam checker I built for my mom.** She pastes a suspicious SMS or WhatsApp message, or uploads a screenshot, and gets a big, clear answer in her own language: **Scam**, **Be careful**, or **Looks OK**. The answer explains why, tells her what to do next, can be read aloud, and has a one-tap button to forward the verdict to me.

Powered by **Gemma**, Google's open-weight model. It works with any OpenAI-compatible endpoint: hosted Gemma, or **Ollama on your own laptop** so private messages never leave the house.

## Features
- 📝 Paste text **or** 📷 upload or paste a screenshot (Gemma is multimodal)
- 🌐 Answers in 12 languages (Hindi, Tamil, Bengali, and more); the chosen language is remembered
- 🔊 Read aloud using the browser's built-in speech engine, which is free
- 📤 "Send to my family" button: WhatsApp or the native share sheet, with a short note written for the son or daughter
- 🔒 Card, Aadhaar, PAN and account numbers are redacted **before** anything reaches the model
- 🧠 Prompt tuned for scams common in India (KYC, UPI collect requests, "digital arrest", courier, task scams, and others), plus the 1930 helpline
- 🗂️ Optional MongoDB Atlas "recent checks" family view, which stores **verdicts only, never messages**

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # then add your key
uvicorn app:app --reload
```
Open http://localhost:8000

### Fully offline / private mode (Ollama)
```bash
ollama pull gemma3:4b
```
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=
LLM_MODEL=gemma3:4b
```
You only change configuration, not code. Swap in any open model you like.

## Deploy on Render
1. Push this repo to GitHub.
2. In Render, choose **New → Blueprint** and pick the repo. It reads `render.yaml`.
3. Set `LLM_API_KEY` to a free Google AI Studio key from https://aistudio.google.com/apikey.

## Stack
FastAPI · vanilla HTML/CSS/JS · Gemma (via the OpenAI-compatible API) · Render · optional MongoDB Atlas

## License
MIT
