"""
Integration Test Suite for AI Call Assistant

Tests every endpoint against the running local server:
  1. GET  /          - Health check
  2. POST /voice     - Inbound call simulation
  3. POST /respond   - Empty speech edge case
  4. POST /respond   - Real speech - Gemini round-trip
  5. POST /respond   - Multi-turn until completion detection
  6. POST /status    - Orphan session cleanup
"""

import sys
import os
import io

# Force UTF-8 output on Windows to avoid cp1252 encoding errors
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests
import xml.etree.ElementTree as ET
import time

BASE = "http://localhost:8000"
FAKE_CALLSID = "CAtestcall_integration_12345"
FAKE_FROM = "+919876543210"

passed = 0
failed = 0


def header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")
        if detail:
            print(f"     -> {detail}")


def parse_xml(text):
    """Parse TwiML XML, return root element."""
    return ET.fromstring(text)


# ─────────────────────────────────────────────────────────────
# TEST 1: Health Check
# ─────────────────────────────────────────────────────────────
header("TEST 1 — Health Check (GET /)")

try:
    r = requests.get(f"{BASE}/")
    check("Status 200", r.status_code == 200, f"Got {r.status_code}")
    check("Body contains 'running'", "running" in r.text.lower(), r.text[:100])
except Exception as e:
    failed += 1
    print(f"  [FAIL] Connection failed: {e}")
    print("\n[ERROR] Server not reachable. Make sure it's running on port 8000.")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# TEST 2: Inbound Call — POST /voice
# ─────────────────────────────────────────────────────────────
header("TEST 2 — Inbound Call (POST /voice)")

r = requests.post(f"{BASE}/voice", data={
    "CallSid": FAKE_CALLSID,
    "From": FAKE_FROM,
})
check("Status 200", r.status_code == 200, f"Got {r.status_code}")
check("Content-Type is XML", "xml" in r.headers.get("content-type", ""), r.headers.get("content-type"))

root = parse_xml(r.text)
check("Root element is <Response>", root.tag == "Response")

# Find <Gather> element
gather = root.find("Gather")
check("<Gather> element exists", gather is not None)

if gather is not None:
    check("Gather input='speech'", gather.get("input") == "speech", gather.get("input"))
    check("Gather language='te-IN'", gather.get("language") == "te-IN", gather.get("language"))
    check("Gather action='/respond'", gather.get("action") == "/respond", gather.get("action"))
    check("Gather speechTimeout='auto'", gather.get("speechTimeout") == "auto", gather.get("speechTimeout"))

    say = gather.find("Say")
    check("<Say> inside <Gather>", say is not None)
    if say is not None:
        check("Greeting mentions 'Yaswanth'", "Yaswanth" in say.text, say.text[:80])
        check("Say voice='Polly.Joanna'", say.get("voice") == "Polly.Joanna", say.get("voice"))

# Check fallback <Say> after <Gather>
all_says = root.findall("Say")
check("Fallback <Say> exists after <Gather>", len(all_says) >= 1)

print(f"\n  [XML] Raw TwiML:\n{r.text[:500]}")


# ─────────────────────────────────────────────────────────────
# TEST 3: Empty Speech Edge Case — POST /respond
# ─────────────────────────────────────────────────────────────
header("TEST 3 — Empty Speech (POST /respond)")

r = requests.post(f"{BASE}/respond", data={
    "CallSid": FAKE_CALLSID,
    "SpeechResult": "",
})
check("Status 200", r.status_code == 200, f"Got {r.status_code}")

root = parse_xml(r.text)
gather = root.find("Gather")
check("<Gather> returned (retry loop)", gather is not None)
if gather is not None:
    say = gather.find("Say")
    check("Retry message present", say is not None and "vinapadaledhu" in (say.text or ""), say.text if say is not None else "None")


# ─────────────────────────────────────────────────────────────
# TEST 4: Real Speech → Gemini Round-Trip — POST /respond
# ─────────────────────────────────────────────────────────────
header("TEST 4 — Gemini Round-Trip (POST /respond)")

r = requests.post(f"{BASE}/respond", data={
    "CallSid": FAKE_CALLSID,
    "SpeechResult": "Nenu Ravi. Yaswanth tho meeting kavali next Monday 3pm ki.",
})
check("Status 200", r.status_code == 200, f"Got {r.status_code}")

root = parse_xml(r.text)

# The AI should either ask a follow-up OR close the conversation.
# Either way, there must be a <Say> somewhere in the response.
has_say = root.find(".//Say") is not None
check("Response contains <Say> (AI reply)", has_say)

# Check if it's a continuation (Gather) or completion (Hangup)
gather = root.find("Gather")
hangup = root.find("Hangup")
check("Response has <Gather> (continue) or <Hangup> (complete)", 
      gather is not None or hangup is not None,
      f"Gather={gather is not None}, Hangup={hangup is not None}")

ai_say = root.find(".//Say")
if ai_say is not None and ai_say.text:
    print(f"\n  [AI] Gemini replied: \"{ai_say.text[:200]}\"")


# ─────────────────────────────────────────────────────────────
# TEST 5: Multi-Turn → Force Completion
# ─────────────────────────────────────────────────────────────
header("TEST 5 — Multi-Turn Completion Test")

# Use a fresh session for this test
COMPLETE_SID = "CAtestcall_completion_67890"

# Step 1: Initiate call
r1 = requests.post(f"{BASE}/voice", data={
    "CallSid": COMPLETE_SID,
    "From": "+919999888877",
})
check("Call initiated", r1.status_code == 200)

# Step 2: Provide enough info to trigger completion
# Give all details in one shot to nudge the model toward closing
r2 = requests.post(f"{BASE}/respond", data={
    "CallSid": COMPLETE_SID,
    "SpeechResult": "Na peru Suresh, nenu Yaswanth friend ni. Rendu appointment kavali, next Wednesday 4pm ki. Please note cheyandi.",
})
check("Response received", r2.status_code == 200)

root2 = parse_xml(r2.text)
ai_say2 = root2.find(".//Say")
hangup2 = root2.find("Hangup")
gather2 = root2.find("Gather")

if ai_say2 is not None and ai_say2.text:
    print(f"  [AI] AI: \"{ai_say2.text[:200]}\"")

# If the model didn't complete yet, send one more nudge
if hangup2 is None and gather2 is not None:
    print("  [INFO] Model wants more info -- sending follow-up...")
    r3 = requests.post(f"{BASE}/respond", data={
        "CallSid": COMPLETE_SID,
        "SpeechResult": "Antha details ichesanu. Please note cheskoni Yaswanth ki cheppandi. Thank you.",
    })
    root3 = parse_xml(r3.text)
    hangup3 = root3.find("Hangup")
    ai_say3 = root3.find(".//Say")
    if ai_say3 is not None and ai_say3.text:
        print(f"  [AI] AI: \"{ai_say3.text[:200]}\"")
    check("Completion detected (Hangup present)", hangup3 is not None, 
          "Model may need more turns -- this is AI-dependent")
else:
    check("Completion detected on first response", hangup2 is not None)


# ─────────────────────────────────────────────────────────────
# TEST 6: Status Callback Cleanup — POST /status
# ─────────────────────────────────────────────────────────────
header("TEST 6 — Status Callback Cleanup (POST /status)")

# First create a session to clean up
ORPHAN_SID = "CAtestcall_orphan_99999"
requests.post(f"{BASE}/voice", data={
    "CallSid": ORPHAN_SID,
    "From": "+910000000000",
})

# Now simulate Twilio reporting the call as completed
r = requests.post(f"{BASE}/status", data={
    "CallSid": ORPHAN_SID,
    "CallStatus": "completed",
})
check("Status 200", r.status_code == 200, f"Got {r.status_code}")
check("Response is valid XML", "<Response/>" in r.text, r.text[:100])


# ─────────────────────────────────────────────────────────────
# TEST 7: Stale Session Recovery — POST /respond with unknown SID
# ─────────────────────────────────────────────────────────────
header("TEST 7 — Stale Session Recovery")

r = requests.post(f"{BASE}/respond", data={
    "CallSid": "CAtestcall_unknown_00000",
    "SpeechResult": "Hello, nenu test caller ni.",
})
check("Status 200 (no crash)", r.status_code == 200, f"Got {r.status_code}")
check("Valid TwiML returned", "<Response>" in r.text, r.text[:100])


# ─────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────
header("TEST SUMMARY")
total = passed + failed
print(f"  Passed: {passed}/{total}")
print(f"  Failed: {failed}/{total}")
print()

if failed == 0:
    print("  ALL TESTS PASSED!")
else:
    print(f"  WARNING: {failed} test(s) need attention.")

sys.exit(0 if failed == 0 else 1)
