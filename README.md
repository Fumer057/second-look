# 🛡️ Second Look

**Second Look** is a multimodal, LLM-powered scam detection service designed for non-technical users. By leveraging Google's **Gemma** open-weight models, it analyzes suspicious SMS, WhatsApp messages, emails, or screenshots and provides a clear, actionable verdict in the user's native language. 

Built with privacy and accessibility in mind, Second Look redacts sensitive PII (Personally Identifiable Information) before inference and can be deployed entirely offline using local LLM runners like Ollama.

## ✨ Features

- **Multimodal Analysis:** Processes both raw text and screenshots (OCR and analysis handled natively by the Gemma vision-language model).
- **Multilingual Output:** Supports 12 languages including English, Hindi, Bengali, Tamil, Telugu, and Marathi.
- **Privacy First:** Client-side and server-side redaction of Credit Card numbers, Aadhaar IDs, PAN cards, and Bank Account numbers before data reaches the model.
- **Omnichannel Access:** 
  - A high-contrast, accessible **Web App**.
  - A WhatsApp-style **Web Chat UI** with conversation memory.
  - A **WhatsApp Bot** integration via the Twilio API.
- **Text-to-Speech (TTS):** Browser-native speech synthesis for visually impaired or elderly users.
- **Flexible LLM Backend:** Compatible with any OpenAI-compatible `/v1/chat/completions` endpoint (Google AI Studio, Ollama, vLLM, OpenRouter).

## 🏗️ Architecture & Stack

- **Backend:** FastAPI (Python)
- **Frontend:** Vanilla HTML5, CSS3, JavaScript
- **Model:** `gemma-4-26b-a4b-it` (MoE) or `gemma-4-31b-it`
- **Database (Optional):** MongoDB Atlas (for anonymized telemetry and language preference storage)
- **Hosting:** Render (via `render.yaml` Blueprint)

## 🚀 Quick Start (Local Development)

### 1. Prerequisites
- Python 3.12+
- Git

### 2. Installation
Clone the repository and set up a virtual environment:

```bash
git clone https://github.com/Fumer057/second-look.git
cd second-look
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configuration
Copy the environment template:
```bash
cp .env.example .env
```
Edit `.env` and add your LLM provider API key (e.g., a free key from [Google AI Studio](https://aistudio.google.com/apikey)):
```env
LLM_API_KEY=your_api_key_here
```

### 4. Run the Server
```bash
uvicorn app:app --reload
```
Navigate to `http://localhost:8000` in your browser.

## 🔒 Offline / Air-Gapped Mode (Ollama)

For maximum privacy, Second Look can run entirely offline on your local machine.

1. Install [Ollama](https://ollama.com/).
2. Pull a Gemma model: `ollama pull gemma3:4b`
3. Update your `.env` file to point to the local instance:
   ```env
   LLM_BASE_URL=http://localhost:11434/v1
   LLM_API_KEY=
   LLM_MODEL=gemma3:4b
   ```

## ☁️ Deployment

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Fumer057/second-look)

1. Click the button above, or go to your Render dashboard, choose **New → Blueprint**, and select your repository.
2. Render will automatically parse the `render.yaml` configuration.
3. Supply your `LLM_API_KEY` in the Render environment variables dashboard.

## 📱 WhatsApp Bot Integration (Twilio)

To enable the WhatsApp bot functionality:
1. Create a [Twilio](https://www.twilio.com/) account and navigate to the **WhatsApp Sandbox**.
2. Add the following to your `.env` or Render environment variables:
   - `TWILIO_ACCOUNT_SID`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_WHATSAPP_FROM` (e.g., `whatsapp:+14155238886`)
3. Set the Twilio Sandbox Webhook URL to `https://your-domain.com/whatsapp`.

## 📜 License
This project is licensed under the MIT License.
