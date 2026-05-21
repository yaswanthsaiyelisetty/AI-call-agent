"""
Quick one-shot WhatsApp test — sends a test message to verify
the Twilio sandbox is properly connected to your phone.
"""

import sys
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
MY_PERSONAL_WHATSAPP = os.getenv("MY_PERSONAL_WHATSAPP", "")
TWILIO_WHATSAPP_SANDBOX_NUMBER = os.getenv(
    "TWILIO_WHATSAPP_SANDBOX_NUMBER", "whatsapp:+14155238886"
)

print(f"Sending test WhatsApp to: {MY_PERSONAL_WHATSAPP}")
print(f"From sandbox number:      {TWILIO_WHATSAPP_SANDBOX_NUMBER}")

try:
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    message = client.messages.create(
        body=(
            "Test message from Yaswanth's AI Call Assistant.\n\n"
            "If you see this, your WhatsApp integration is working!"
        ),
        from_=TWILIO_WHATSAPP_SANDBOX_NUMBER,
        to=MY_PERSONAL_WHATSAPP,
    )
    print(f"\n[SUCCESS] Message sent!")
    print(f"  SID:    {message.sid}")
    print(f"  Status: {message.status}")
    print(f"\nCheck your WhatsApp now!")

except Exception as e:
    print(f"\n[ERROR] Failed to send: {e}")
    sys.exit(1)
