# 📞 Yaswanth's AI Call Assistant

An AI-powered phone secretary that answers incoming Twilio calls in **Telugu (Manglish)**, conducts a natural conversation using **Google Gemini 1.5 Flash**, collects caller details, and instantly sends a structured summary to your **WhatsApp**.

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

### 3. Run the server

```bash
python main.py
# Or directly:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Expose to Twilio

Use [ngrok](https://ngrok.com) to tunnel your local server:

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL and set it in your Twilio phone number config:
- **Voice webhook**: `https://xxxx.ngrok.io/voice` (HTTP POST)
- **Status callback** (optional): `https://xxxx.ngrok.io/status` (HTTP POST)

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
2. **Greeting** → TwiML responds with a Telugu greeting inside a `<Gather>` block (speech input, te-IN language model).
3. **Conversation loop** → Each speech segment POSTs to `/respond`. Gemini generates a context-aware Telugu reply. Loop continues via nested `<Gather>` blocks.
4. **Completion** → When Gemini's reply contains terminal phrases (e.g., "note cheskunnanu"), the server returns `<Say>` + `<Hangup/>`.
5. **WhatsApp summary** → A background thread asks Gemini to distill the transcript into Caller Name / Purpose / Appointment Details, then sends it via Twilio WhatsApp API.
