"""
Live Meta WhatsApp Cloud API Verification Script.
Executes an actual outbound message check to Meta Graph API v20.0.

Usage:
  set META_PHONE_NUMBER_ID=your_id
  set META_ACCESS_TOKEN=your_token
  set META_RECIPIENT_PHONE=919876543210
  python scripts/verify_live_whatsapp.py
"""

import os
import sys
import requests

phone_id = os.environ.get("META_PHONE_NUMBER_ID")
token = os.environ.get("META_ACCESS_TOKEN")
recipient = os.environ.get("META_RECIPIENT_PHONE")

print("=" * 70)
print("VYZN NETRA — LIVE META WHATSAPP VERIFICATION UTILITY")
print("=" * 70)

if not all([phone_id, token, recipient]):
    print("\n[DIAGNOSTIC NOTICE] Missing Live Meta Credentials in Environment.")
    print("To test live message delivery to an actual smartphone:")
    print("  1. Log into developers.facebook.com -> WhatsApp -> API Setup.")
    print("  2. Copy Phone number ID and Temporary Access Token.")
    print("  3. Set environment variables:")
    print("     $env:META_PHONE_NUMBER_ID = 'your_phone_id'")
    print("     $env:META_ACCESS_TOKEN = 'your_access_token'")
    print("     $env:META_RECIPIENT_PHONE = '9198XXXXXXXX'")
    print("  4. Re-run this utility.\n")
    print("Architecture Note: In local/offline mode, WhatsAppCloudProvider safely")
    print("simulates delivery and logs complete JSON payloads for audit validation.")
    sys.exit(0)

print(f"[*] Testing connection with Phone ID: {phone_id}")
print(f"[*] Sending test alert to: {recipient}...")

url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

payload = {
    "messaging_product": "whatsapp",
    "recipient_type": "individual",
    "to": recipient,
    "type": "text",
    "text": {
        "preview_url": False,
        "body": "🚨 *VYZN Netra Security Alert*\nTest dispatch from edge node.\nStatus: Edge Online (Nagpur Hub)"
    }
}

try:
    resp = requests.post(url, json=payload, headers=headers, timeout=10.0)
    print(f"[*] HTTP Status Code: {resp.status_code}")
    print(f"[*] Response Body: {resp.text}")
    if resp.status_code in (200, 201):
        print("\n[SUCCESS] Live WhatsApp message delivered successfully!")
    else:
        print("\n[META API ERROR] Review Meta error code above (e.g. expired token or unverified recipient).")
except Exception as e:
    print(f"\n[NETWORK FAILURE] Could not reach Meta Graph API: {e}")