# 📞 Yaswanth's AI Call Assistant

An AI-powered phone secretary that answers incoming Twilio calls in **Telugu (Manglish)**, conducts a natural conversation using **Google Gemini 2.5 Flash**, collects caller details, and instantly sends a structured summary to your **WhatsApp**.

## Architecture

```
Incoming Call → Twilio → /voice (greeting + Gather)
                              ↓
                   Caller speaks (te-IN ASR)
                              ↓
                  /respond (Gemini processes → TwiML reply)
                              ↓  ← loops until info gathered
                   Completion detected
                              ↓
                  <Say> farewell → <Hangup/>
                              ↓
               Background thread → Gemini summarizes
                              ↓
               Twilio WhatsApp API → Your phone
```

## Quick Start

### 1. Clone & install

```bash
cd c:\projects\voice_agent
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Configure secrets

```bash
copy .env.example .env
# Edit .env with your actual credentials
```

### 3. Twilio WhatsApp Sandbox Opt-In (IMPORTANT)

Before you can receive WhatsApp messages, you must authorize the Twilio Sandbox:
1. Open WhatsApp on your phone.
2. Send a message to **+1 415 523 8886** (or your Twilio Sandbox number).
3. The message must be your join code found in the Twilio Console (e.g., `join hungry-elephant`).
4. Wait for the confirmation reply from Twilio.

### 4. Run the server

```bash
python main.py
# Or directly:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Expose to Twilio

Use [ngrok](https://ngrok.com) to tunnel your local server:

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok.dev` URL and set it in your Twilio phone number config:
- **Voice webhook**: `https://xxxx.ngrok.dev/voice` (HTTP POST)
- **Status callback** (optional): `https://xxxx.ngrok.dev/status` (HTTP POST)

## Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key from [AI Studio](https://aistudio.google.com/apikey) |
| `TWILIO_ACCOUNT_SID` | From [Twilio Console](https://console.twilio.com) |
| `TWILIO_AUTH_TOKEN` | From Twilio Console |
| `MY_PERSONAL_WHATSAPP` | Your WhatsApp number (`whatsapp:+91XXXXXXXXXX`) |
| `TWILIO_WHATSAPP_SANDBOX_NUMBER` | Twilio sandbox sender (default: `whatsapp:+14155238886`) |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/voice` | Inbound call webhook — greets caller, starts Gather |
| `POST` | `/respond` | Speech processing loop — Gemini conversation |
| `POST` | `/status` | Optional call status cleanup callback |

## How It Works

1. **Call arrives** → Twilio POSTs to `/voice` with `CallSid` and `From`.
2. **Greeting** → TwiML responds with a Telugu greeting using the `Polly.Aditi` Indian English voice (ideal for Manglish). Twilio listens via a `<Gather>` block (te-IN ASR model) configured with robust timeouts to prevent cutting callers off.
3. **Conversation loop** → Each speech segment POSTs to `/respond`. Gemini generates a context-aware Telugu reply. If the caller is silent, the system seamlessly redirects to prevent the call from dropping abruptly.
4. **Completion** → When Gemini's reply contains terminal phrases (e.g., "note cheskunnanu"), the server returns `<Say>` + `<Hangup/>`.
5. **WhatsApp summary** → A background thread asks Gemini to distill the transcript into Caller Name / Purpose / Appointment Details, then sends it via Twilio WhatsApp API.
