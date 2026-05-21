"""
╔══════════════════════════════════════════════════════════════════════╗
║  AI Call Assistant — Yaswanth's Personal Telugu Secretary           ║
║                                                                    ║
║  Picks up incoming Twilio calls, conducts a Telugu conversation    ║
║  via Google Gemini, gathers caller intent/details, hangs up,      ║
║  and sends a structured WhatsApp summary to Yaswanth.             ║
║                                                                    ║
║  Stack: FastAPI · Uvicorn · Twilio Voice/WhatsApp · Gemini 1.5    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ─────────────────────────────────────────────────
import os
import logging
import threading
from typing import Optional

# ── Third-Party ──────────────────────────────────────────────────────
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Response
from fastapi.responses import PlainTextResponse
import google.generativeai as genai
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Gather

# ── Bootstrap ────────────────────────────────────────────────────────
load_dotenv()  # Loads .env file into os.environ

# ── Logging Setup ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("voice_agent")

# ══════════════════════════════════════════════════════════════════════
# SECTION 1 — Environment Variables & Validation
# ══════════════════════════════════════════════════════════════════════

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
MY_PERSONAL_WHATSAPP: str = os.getenv("MY_PERSONAL_WHATSAPP", "")
TWILIO_WHATSAPP_SANDBOX_NUMBER: str = os.getenv(
    "TWILIO_WHATSAPP_SANDBOX_NUMBER", "whatsapp:+14155238886"
)

# Fail-fast if any critical secret is missing at startup.
_REQUIRED_VARS = {
    "GOOGLE_API_KEY": GOOGLE_API_KEY,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "MY_PERSONAL_WHATSAPP": MY_PERSONAL_WHATSAPP,
}
for _var_name, _var_val in _REQUIRED_VARS.items():
    if not _var_val:
        raise RuntimeError(
            f"Missing required environment variable: {_var_name}. "
            f"Copy .env.example to .env and fill in your credentials."
        )

# ══════════════════════════════════════════════════════════════════════
# SECTION 2 — Gemini Configuration
# ══════════════════════════════════════════════════════════════════════

genai.configure(api_key=GOOGLE_API_KEY)

# The system prompt establishes the AI's persona, language rules, and
# the strict state-machine flow it must follow during every call.
SYSTEM_PROMPT: str = (
    "Nuvvu Yaswanth ki personal secretary vi. "
    "Yaswanth busy ga vunnaru, andukani nuvvu call attend chesthunnav. "
    "Nee job enti ante — caller enduku call chesaro teluskoni, vaalla name, "
    "Yaswanth tho vaalla relation, and emaina appointment or meeting kavali ante "
    "aa details anni collect cheyyali.\n\n"
    "IMPORTANT RULES:\n"
    "1. Nuvvu ALWAYS Latinized Telugu (Manglish) lo maatladali — "
    "English letters lo Telugu words raayali. Example: 'Namaskaram andi, "
    "miru enduku call chesaro cheppagalara?'\n"
    "2. Markdown use cheyyaddu — no asterisks (*), no hashtags (#), "
    "no bold formatting. Plain text only.\n"
    "3. Prati response lo MAXIMUM 2 sentences matrame cheppu. "
    "Ekkuva matladaku — idi real-time phone call, latency takkuva undali.\n"
    "4. Conversation flow:\n"
    "   a. Modatiga caller enduku call chesaro adugu.\n"
    "   b. Vaallaki appointment or meeting kavali ante, vaalla NAME adugu "
    "and Yaswanth ki vaaru em avutharo (relation/purpose) adugu.\n"
    "   c. Details anni collect ayyaka, final response lo ee line undali: "
    "'Thank you andi. Nenu complete details note cheskunnanu, "
    "Yaswanth ki mi gurinchi tappakunda chebuthanu.'\n"
    "5. Caller ki polite ga, friendly ga maatladu — professional but warm.\n"
    "6. Entha information collect cheyyagalavo antha try cheyyi, "
    "but caller ni irritate cheyyaddu — vaaru cheppindi chaalu ante accept cheyyi."
)

gemini_model = genai.GenerativeModel("gemini-2.5-flash")

# ══════════════════════════════════════════════════════════════════════
# SECTION 3 — In-Memory Session Store
# ══════════════════════════════════════════════════════════════════════

# Maps each active call's CallSid → session dict.
# Structure per session:
#   {
#       "caller": "+91...",           — The caller's phone number
#       "history": [                  — Gemini multi-turn history
#           {"role": "user",  "parts": ["<system prompt>"]},
#           {"role": "model", "parts": ["<greeting>"]},
#           {"role": "user",  "parts": ["<caller speech>"]},
#           ...
#       ]
#   }
#
# NOTE: This is intentionally in-memory for single-instance deployments.
# For horizontal scaling, swap this dict with Redis or a database.
call_sessions: dict[str, dict] = {}

# ══════════════════════════════════════════════════════════════════════
# SECTION 4 — Twilio Client (Lazy Singleton)
# ══════════════════════════════════════════════════════════════════════

# Instantiated once at module load — the SDK is thread-safe.
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ══════════════════════════════════════════════════════════════════════
# SECTION 5 — FastAPI Application
# ══════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Yaswanth AI Call Assistant",
    description="Answers calls in Telugu, gathers info, sends WhatsApp summary.",
    version="1.0.0",
)


# ── Health Check ─────────────────────────────────────────────────────
@app.get("/", response_class=PlainTextResponse)
async def health_check():
    """Simple liveness probe — confirms the server is up."""
    return "Voice Agent is running."


# ══════════════════════════════════════════════════════════════════════
# ENDPOINT 1 — /voice  (Inbound Call Intercept)
# ══════════════════════════════════════════════════════════════════════

@app.post("/voice")
async def handle_incoming_call(
    CallSid: str = Form(...),
    From: str = Form(default="Unknown"),
):
    """
    Twilio hits this webhook when an inbound call arrives.

    Responsibilities:
    1. Create a fresh in-memory session for this CallSid.
    2. Return TwiML that greets the caller in Telugu and begins
       speech-gathering with the Indian-Telugu acoustic model.
    """
    logger.info("📞 Incoming call | CallSid=%s | From=%s", CallSid, From)

    # ── Initialize session ───────────────────────────────────────────
    # The system prompt is injected as the first "user" message so that
    # Gemini treats all subsequent exchanges within this persona context.
    call_sessions[CallSid] = {
        "caller": From,
        "history": [
            {"role": "user", "parts": [SYSTEM_PROMPT]},
        ],
    }

    # ── Build TwiML greeting ─────────────────────────────────────────
    greeting_text = (
        "Hi, Yaswanth busy ga vunnaru. "
        "Miru ey pani medha call chesaro koncham cheppagalara?"
    )

    # Append the greeting to history as the model's first response so
    # that Gemini's context stays consistent with what the caller heard.
    call_sessions[CallSid]["history"].append(
        {"role": "model", "parts": [greeting_text]}
    )

    response = VoiceResponse()

    # <Gather> tells Twilio to listen for the caller's speech.
    # - input="speech"    → use speech recognition, not DTMF.
    # - language="te-IN"  → Telugu acoustic model for accurate ASR.
    # - speechTimeout="auto" → Twilio auto-detects end of utterance.
    # - action="/respond"  → POST the transcribed speech here next.
    gather = Gather(
        input="speech",
        action="/respond",
        timeout=7,
        speech_timeout=2,
        language="te-IN",
    )
    gather.say(greeting_text, voice="Polly.Aditi")
    response.append(gather)

    # Fallback: if Gather times out without any speech detected,
    # politely ask the caller to speak again.
    response.say(
        "Naku emi vinapadaledhu andi. Malli cheppandi.",
        voice="Polly.Aditi",
    )
    response.redirect("/voice")

    logger.info("✅ Session created & greeting sent | CallSid=%s", CallSid)
    return Response(content=str(response), media_type="application/xml")


# ══════════════════════════════════════════════════════════════════════
# ENDPOINT 2 — /respond  (Conversational Processing Loop)
# ══════════════════════════════════════════════════════════════════════

@app.post("/respond")
async def handle_caller_response(
    CallSid: str = Form(...),
    SpeechResult: Optional[str] = Form(default=None),
):
    """
    Twilio posts here after each <Gather> captures caller speech.

    Responsibilities:
    1. Validate that we received a usable transcription.
    2. Feed the full conversation history to Gemini for a reply.
    3. Detect completion indicators → hangup + WhatsApp dispatch.
    4. Otherwise, loop back with another <Gather> to keep talking.
    """
    logger.info(
        "🎤 Speech received | CallSid=%s | SpeechResult=%s",
        CallSid,
        SpeechResult,
    )

    response = VoiceResponse()

    # ── Edge Case: No transcription received ─────────────────────────
    if not SpeechResult or not SpeechResult.strip():
        logger.warning("⚠️  Empty SpeechResult — asking caller to repeat.")
        gather = Gather(
            input="speech",
            action="/respond",
            timeout=7,
            speech_timeout=2,
            language="te-IN",
        )
        gather.say(
            "Naku emi vinapadaledhu andi. Malli cheppandi.",
            voice="Polly.Aditi",
        )
        response.append(gather)
        response.redirect("/respond")
        return Response(content=str(response), media_type="application/xml")

    # ── Edge Case: Session not found (stale/restarted server) ────────
    if CallSid not in call_sessions:
        logger.error("❌ No session found for CallSid=%s — creating fallback.", CallSid)
        call_sessions[CallSid] = {
            "caller": "Unknown",
            "history": [
                {"role": "user", "parts": [SYSTEM_PROMPT]},
            ],
        }

    session = call_sessions[CallSid]

    # ── Append caller's speech to conversation history ───────────────
    session["history"].append(
        {"role": "user", "parts": [SpeechResult.strip()]}
    )

    # ── Call Gemini with the full multi-turn history ─────────────────
    ai_reply = _get_gemini_response(session["history"])
    logger.info("🤖 Gemini reply | CallSid=%s | Reply=%s", CallSid, ai_reply)

    # ── Append AI reply to history for context continuity ────────────
    session["history"].append(
        {"role": "model", "parts": [ai_reply]}
    )

    # ── Check for conversation completion indicators ─────────────────
    if _is_conversation_complete(ai_reply):
        logger.info("🏁 Conversation complete — hanging up | CallSid=%s", CallSid)

        # Say the final farewell message to the caller.
        response.say(ai_reply, voice="Polly.Aditi")

        # Drop the phone line.
        response.hangup()

        # Fire WhatsApp notification on a background thread so we don't
        # block the TwiML response. Twilio needs the XML back fast.
        _dispatch_whatsapp_async(
            caller_number=session["caller"],
            conversation_history=session["history"],
        )

        # Clean up the session — call is over.
        call_sessions.pop(CallSid, None)

        return Response(content=str(response), media_type="application/xml")

    # ── Conversation still active — loop back with another Gather ────
    gather = Gather(
        input="speech",
        action="/respond",
        timeout=7,
        speech_timeout=2,
        language="te-IN",
    )
    gather.say(ai_reply, voice="Polly.Aditi")
    response.append(gather)

    # Fallback if Gather times out again.
    response.say(
        "Naku emi vinapadaledhu andi. Malli cheppandi.",
        voice="Polly.Aditi",
    )
    response.redirect("/respond")

    return Response(content=str(response), media_type="application/xml")


# ══════════════════════════════════════════════════════════════════════
# SECTION 6 — Gemini Interaction Helpers
# ══════════════════════════════════════════════════════════════════════

def _get_gemini_response(history: list[dict]) -> str:
    """
    Send the full conversation history to Gemini and return its text reply.

    The history list follows Gemini's multi-turn format:
        [{"role": "user"|"model", "parts": ["..."]}]

    On any API failure, returns a graceful fallback message so the call
    doesn't crash — the caller just hears a retry prompt.
    """
    try:
        chat = gemini_model.start_chat(history=history[:-1])
        # Send the latest user message explicitly to get a response.
        latest_message = history[-1]["parts"][0]
        response = chat.send_message(latest_message)

        # Strip any accidental markdown the model might produce.
        reply_text = response.text.strip()
        reply_text = _sanitize_markdown(reply_text)

        return reply_text

    except Exception as exc:
        logger.exception("❌ Gemini API error: %s", exc)
        return (
            "Sorry andi, oka technical problem vachindi. "
            "Malli cheppagalara please?"
        )


def _sanitize_markdown(text: str) -> str:
    """
    Remove any markdown artifacts that Gemini might inject despite
    the system prompt telling it not to. This ensures clean TTS output.
    """
    # Remove bold/italic markers.
    text = text.replace("**", "").replace("*", "")
    # Remove heading markers.
    text = text.replace("##", "").replace("#", "")
    # Remove bullet markers at line starts.
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- "):
            stripped = stripped[2:]
        cleaned_lines.append(stripped)
    return " ".join(cleaned_lines).strip()


def _is_conversation_complete(ai_reply: str) -> bool:
    """
    Detect whether the AI's reply signals that all required information
    has been gathered and the call should end.

    Checks for known terminal phrases (case-insensitive) that the
    system prompt instructs the model to use upon completion.
    """
    reply_lower = ai_reply.lower()

    completion_phrases = [
        "thank you andi",
        "note cheskunnanu",
        "tappakunda chebuthanu",
        "details note cheskunn",
        "complete details",
    ]

    return any(phrase in reply_lower for phrase in completion_phrases)


# ══════════════════════════════════════════════════════════════════════
# SECTION 7 — WhatsApp Notification Dispatch
# ══════════════════════════════════════════════════════════════════════

def _dispatch_whatsapp_async(
    caller_number: str, conversation_history: list[dict]
) -> None:
    """
    Launch the WhatsApp summary workflow on a daemon background thread.

    This is non-blocking so the TwiML <Hangup/> response reaches Twilio
    without delay. The thread is marked as a daemon so it won't prevent
    the server process from shutting down.
    """
    thread = threading.Thread(
        target=trigger_whatsapp_notification,
        args=(caller_number, conversation_history),
        daemon=True,
    )
    thread.start()
    logger.info("📤 WhatsApp dispatch thread launched for caller=%s", caller_number)


def trigger_whatsapp_notification(
    caller_number: str, conversation_history: list[dict]
) -> None:
    """
    Core WhatsApp notification pipeline:

    1. Flatten the entire conversation into a readable transcript.
    2. Ask Gemini to distill it into a structured 3-line summary:
       - Caller Name
       - Purpose / Motive of the call
       - Appointment Request Details
    3. Send the summary to Yaswanth's WhatsApp via Twilio.
    """
    try:
        # ── Step 1: Flatten conversation into a transcript string ────
        transcript_lines = []
        for entry in conversation_history:
            role_label = "Caller" if entry["role"] == "user" else "Secretary"
            # Skip the system prompt (first entry) in the transcript.
            if entry == conversation_history[0]:
                continue
            text = entry["parts"][0] if entry["parts"] else ""
            transcript_lines.append(f"{role_label}: {text}")

        full_transcript = "\n".join(transcript_lines)

        logger.info(
            "📝 Generating WhatsApp summary for caller=%s\nTranscript:\n%s",
            caller_number,
            full_transcript,
        )

        # ── Step 2: Ask Gemini to produce a clean summary ────────────
        summary_prompt = (
            "Below is a phone call transcript between a caller and "
            "Yaswanth's AI secretary. Extract and format EXACTLY these "
            "3 lines — nothing else, no markdown, no extra commentary:\n\n"
            "Caller Name: <name or 'Not provided'>\n"
            "Purpose: <why they called, in one sentence>\n"
            "Appointment Details: <requested time/date or 'None requested'>\n\n"
            f"Caller Phone Number: {caller_number}\n\n"
            "--- TRANSCRIPT ---\n"
            f"{full_transcript}\n"
            "--- END TRANSCRIPT ---"
        )

        summary_response = gemini_model.generate_content(summary_prompt)
        summary_text = summary_response.text.strip()
        summary_text = _sanitize_markdown(summary_text)

        logger.info("📋 Summary generated:\n%s", summary_text)

        # ── Step 3: Compose and send the WhatsApp message ────────────
        whatsapp_body = (
            "📞 *New Call Summary*\n"
            f"From: {caller_number}\n\n"
            f"{summary_text}\n\n"
            "— Yaswanth's AI Secretary"
        )

        message = twilio_client.messages.create(
            body=whatsapp_body,
            from_=TWILIO_WHATSAPP_SANDBOX_NUMBER,
            to=MY_PERSONAL_WHATSAPP,
        )

        logger.info(
            "✅ WhatsApp sent successfully | SID=%s | To=%s",
            message.sid,
            MY_PERSONAL_WHATSAPP,
        )

    except Exception as exc:
        # Catch-all: log the error but NEVER let this crash the server.
        # The call has already been handled; this is a best-effort notification.
        logger.exception(
            "❌ WhatsApp notification failed for caller=%s: %s",
            caller_number,
            exc,
        )


# ══════════════════════════════════════════════════════════════════════
# SECTION 8 — Call Status Callback (Optional Cleanup)
# ══════════════════════════════════════════════════════════════════════

@app.post("/status")
async def handle_call_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(default="unknown"),
):
    """
    Optional Twilio StatusCallback endpoint.

    Cleans up any orphaned sessions when Twilio reports the call as
    completed, busy, no-answer, or failed. This prevents memory leaks
    from calls that disconnect unexpectedly (e.g., caller hangs up
    mid-conversation before the AI triggers the normal cleanup).

    Configure this in your Twilio phone number settings:
        StatusCallback URL = https://your-domain.com/status
    """
    logger.info(
        "📊 Call status update | CallSid=%s | Status=%s",
        CallSid,
        CallStatus,
    )

    terminal_statuses = {"completed", "busy", "no-answer", "failed", "canceled"}

    if CallStatus.lower() in terminal_statuses:
        removed = call_sessions.pop(CallSid, None)
        if removed:
            logger.info("🧹 Cleaned up orphaned session | CallSid=%s", CallSid)

    return Response(content="<Response/>", media_type="application/xml")


# ══════════════════════════════════════════════════════════════════════
# SECTION 9 — Entrypoint
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    logger.info("🚀 Starting Voice Agent server on port 8000...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Auto-reload during development. Disable in prod.
        log_level="info",
    )
