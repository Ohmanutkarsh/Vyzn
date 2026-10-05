"""
Outbound SMS Service for VYZN Netra.
Dispatches real 6-digit phone verification OTP codes to Indian & international mobile numbers via:
1. Fast2SMS (popular, instant OTP gateway for Indian mobile numbers +91)
2. Twilio SMS (international & Indian mobile numbers)
3. Supabase Phone OTP (if configured)
"""

from __future__ import annotations
import os
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("vyzn.sms")


def get_sms_provider_status() -> Dict[str, Any]:
    """Returns configured SMS providers."""
    has_fast2sms = bool(os.environ.get("FAST2SMS_API_KEY"))
    has_twilio = bool(
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
        and os.environ.get("TWILIO_PHONE_NUMBER")
    )
    has_supabase = bool(os.environ.get("VYZN_SUPABASE_URL") and os.environ.get("VYZN_SUPABASE_ANON_KEY"))
    configured = has_fast2sms or has_twilio or has_supabase
    provider = "fast2sms" if has_fast2sms else ("twilio" if has_twilio else ("supabase" if has_supabase else "none"))
    return {
        "configured": configured,
        "provider": provider,
        "has_fast2sms": has_fast2sms,
        "has_twilio": has_twilio,
        "has_supabase": has_supabase
    }


def send_phone_otp_sms(phone_e164: str, code: str) -> Dict[str, Any]:
    """
    Sends real SMS with 6-digit OTP code to mobile number.
    """
    phone = phone_e164.strip()
    clean_digits = "".join(ch for ch in phone if ch.isdigit())
    if clean_digits.startswith("91") and len(clean_digits) == 12:
        digits_10 = clean_digits[2:]
    else:
        digits_10 = clean_digits[-10:]

    # 1. Fast2SMS (Optimized for Indian +91 mobile numbers)
    fast2sms_key = os.environ.get("FAST2SMS_API_KEY")
    if fast2sms_key:
        try:
            resp = requests.post(
                "https://www.fast2sms.com/dev/bulkV2",
                headers={
                    "authorization": fast2sms_key,
                    "Content-Type": "application/json"
                },
                json={
                    "variables_values": code,
                    "route": "otp",
                    "numbers": digits_10
                },
                timeout=10.0
            )
            data = resp.json() if resp.text else {}
            if data.get("return") is True:
                logger.info(f"[SMS] Sent real OTP to {phone} via Fast2SMS")
                return {"sent": True, "provider": "fast2sms", "phone": phone}
            else:
                logger.warning(f"[SMS] Fast2SMS dispatch response: {data}")
        except Exception as e:
            logger.error(f"[SMS] Fast2SMS dispatch failed: {e}")

    # 2. Twilio SMS
    twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    twilio_token = os.environ.get("TWILIO_AUTH_TOKEN")
    twilio_from = os.environ.get("TWILIO_PHONE_NUMBER")
    if twilio_sid and twilio_token and twilio_from:
        try:
            resp = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json",
                auth=(twilio_sid, twilio_token),
                data={
                    "From": twilio_from,
                    "To": phone,
                    "Body": f"{code} is your VYZN mobile verification code. Valid for 5 minutes."
                },
                timeout=10.0
            )
            if resp.status_code in [200, 201]:
                logger.info(f"[SMS] Sent real OTP to {phone} via Twilio")
                return {"sent": True, "provider": "twilio", "phone": phone}
            else:
                logger.warning(f"[SMS] Twilio dispatch returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[SMS] Twilio dispatch failed: {e}")

    # 3. Supabase Phone OTP
    supabase_url = os.environ.get("VYZN_SUPABASE_URL", "").rstrip("/")
    supabase_anon_key = os.environ.get("VYZN_SUPABASE_ANON_KEY", "")
    if supabase_url and supabase_anon_key:
        try:
            resp = requests.post(
                f"{supabase_url}/auth/v1/otp",
                headers={"apikey": supabase_anon_key, "Content-Type": "application/json"},
                json={"phone": phone, "create_user": True},
                timeout=10.0
            )
            if resp.status_code in [200, 201]:
                logger.info(f"[SMS] Sent OTP to {phone} via Supabase Phone Auth")
                return {"sent": True, "provider": "supabase", "phone": phone}
            else:
                logger.warning(f"[SMS] Supabase Phone OTP returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[SMS] Supabase Phone OTP dispatch error: {e}")

    logger.warning(f"[SMS] No live SMS gateway configured. Code for {phone}: {code}")
    return {
        "sent": False,
        "provider": "none",
        "message": "Configure FAST2SMS_API_KEY or Twilio credentials in .env to send real SMS."
    }
