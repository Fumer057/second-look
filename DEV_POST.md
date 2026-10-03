---
title: I Built My Mom a "Second Look" Button for Scam Messages, Powered by Gemma
published: false
tags: devchallenge, weekendchallenge, hf26challenge
---

*This is a submission for the [Hacktoberfest Weekend Challenge: Build for a Friend](https://dev.to/challenges/hacktoberfest-weekend-2026-10-01)*

<!-- ✏️ Replace everything in [BRACKETS] with your real story. Judges weight WRITING most heavily, so the more specific and personal this is, the better. -->

## What I Built

My mom gets at least [N] suspicious messages a week. "Your electricity will be disconnected tonight." "Your SBI KYC is expiring, click here." "Your parcel is held at customs." And once, a call from a "police officer" who said she was under *digital arrest*.

She's smart, but she isn't a tech person, and these messages are built to make you panic. Her system until now: screenshot the message, send it to me, and wait. If I was in a meeting she waited hours, worrying. [Add a real incident here: the time she almost paid, or the time a relative lost money.]

So this weekend I built her **Second Look**, a one-page app with a single job:

> Paste the message (or drop a screenshot), and get a big, clear answer in your own language.

- 🚨 **SCAM: Do not reply** / ⚠️ **BE CAREFUL** / ✅ **Looks OK**
- A short list of *why*, in plain words ("Banks never ask for your PIN to *receive* money")
- A short list of *what to do now* (including the 1930 cybercrime helpline if she already clicked)
- 🔊 **Read aloud**, because small text is hard to read
- 📤 **Send to my family**, which forwards the verdict to me on WhatsApp so I stay in the loop without being the bottleneck
- It answers in [Hindi/Tamil/...]. She picks it once and the app remembers.

## Demo

🔗 **Live:** [your-app.onrender.com]

<!-- Add a 30–60 second screen recording (Loom/YouTube) or 2–3 screenshots: the input screen, a SCAM verdict, the WhatsApp share. -->

## Code

{% github [your-username]/second-look %}

## How I Built It

The stack is deliberately small, because I wanted it finished this weekend and simple enough for her to use:

- **Model:** [Gemma](https://ai.google.dev/gemma), Google's open-weight model. I call it through an OpenAI-compatible endpoint, which means the *same code* talks to hosted Gemma on Google AI Studio, to **Ollama on my laptop**, or to vLLM/OpenRouter. Switching is one environment variable.
- **Multimodal:** Most scams reach her as WhatsApp forwards, so screenshot input mattered more than text. Gemma reads the image directly, so I didn't need a separate OCR step.
- **Backend:** FastAPI, about 200 lines. It redacts card, Aadhaar, PAN and account numbers *before* anything reaches the model, builds the prompt, and parses Gemma's JSON verdict defensively (it strips code fences, normalizes the verdict, and falls back to the next model if one fails).
- **Frontend:** Plain HTML, CSS and JS. Big type, high contrast, one button. Read-aloud uses the browser's built-in `speechSynthesis`, so it costs nothing and needs no extra API.
- **Hosting:** Render, deployed with a `render.yaml` blueprint.

### The prompt is the product
Most of the work went into the prompt rather than the code. I gave Gemma a field guide to the scams that actually reach my mom: fake KYC, UPI "collect" requests ("enter your PIN to receive ₹5,000"), courier and customs fees, "digital arrest" by fake police, task-based job scams, and AnyDesk/APK links. I also gave it rules a worried parent needs: **never say 100% safe**, use short sentences, never make her feel stupid, and if she has already paid or shared an OTP, tell her exactly what to do *right now*.

One gotcha: Gemma's chat template has no `system` role, so all instructions go into the user turn. That approach works on every provider.

## Why Does Open Innovation Matter?

Look at what my mom pastes into this app. It includes her bank's name, partial account numbers, OTPs, phone numbers, and sometimes the names of relatives. **That is exactly the data that shouldn't go to a server neither of us controls.**

Gemma's open weights let me fix that:

1. **It can run entirely at home.** With `ollama pull gemma3:4b` and one changed URL, the whole thing runs on our family laptop with no internet. Her messages never leave the house. A closed API can't offer that at all.
2. **It costs nothing.** No per-message bill to keep an eye on. She can check every silly forward without anyone worrying about tokens.
3. **I control the behavior.** I can tune the prompt for *Indian* scams in *her* language, swap to a smaller model for an old phone, or later fine-tune it on the scam screenshots our family group collects. I'm not stuck with whatever a vendor decides.
4. **It won't disappear.** A model I can download today will still work in five years. A free tier might not.

The hosted demo uses Gemma on Google AI Studio so judges can try it. The version on Mom's laptop runs locally.

## Handing It Over

<!-- ⭐ Bonus points. Write this section for real. -->
I sat down with Mom on [day], opened the app on her phone, and added it to her home screen. [What she tested first. What she said. Did she laugh, get confused, or ask for something? Did she use it on her own afterwards? Quote her exactly if you can.]

[What you changed after watching her use it. For example: "She couldn't find the upload button, so I made it bigger" or "She asked for Hindi, so I added language memory."]

## My Agent Session

<!-- Optional: export your session with DevRelay and embed it with the agent_session tag, or link it. -->

## Prize Categories

- **Best Use of Gemma**: Gemma is the core: multimodal scam analysis, multilingual output, and an offline mode via Ollama
- **Best Use of Render**: hosted on Render with a one-click `render.yaml` blueprint
<!-- - **Best Use of MongoDB Atlas**: only if you enable MONGODB_URI for the anonymized family "recent checks" view -->
