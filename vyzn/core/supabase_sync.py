"""
Supabase Cloud Synchronization Service for VYZN Netra.
Handles storing user login records, mobile numbers, email verifications, and audit history
directly in Supabase PostgreSQL database with zero state leakage and graceful local fallback.
"""

from __future__ import annotations
import os
import time
import logging
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except Exception:
    pass

logger = logging.getLogger("vyzn.supabase_sync")


def get_supabase_url() -> str:
    """Returns normalized Supabase project base URL."""
    url = (os.environ.get("VYZN_SUPABASE_URL") or os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[:-len("/rest/v1")].rstrip("/")
    return url


def get_supabase_key() -> str:
    """Returns Supabase Service Role Key (preferred for backend sync) or Anon Key."""
    return (
        os.environ.get("VYZN_SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("VYZN_SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or ""
    ).strip()


def is_supabase_configured() -> bool:
    """Returns True if valid Supabase URL and API Key are configured in environment."""
    url = get_supabase_url()
    key = get_supabase_key()
    return bool(url and key and url.startswith("http"))


def get_supabase_headers() -> Dict[str, str]:
    """Generates standard PostgREST headers for Supabase API requests."""
    key = get_supabase_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation"
    }


def sync_user_to_supabase(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upserts user login info and verification status to the `vyzn_users` table in Supabase.
    If Supabase is not configured, returns graceful fallback result.
    """
    if not is_supabase_configured():
        logger.info(f"[SUPABASE] Local mode: Supabase not configured. Skipping remote sync for user {user.get('email')}")
        return {
            "synced": False,
            "reason": "supabase_not_configured",
            "message": "Set VYZN_SUPABASE_URL and VYZN_SUPABASE_ANON_KEY in .env to enable remote sync."
        }

    base_url = get_supabase_url()
    headers = get_supabase_headers()
    email = user.get("email", "").strip().lower()
    now_iso = datetime.now(timezone.utc).isoformat()

    update_payload = {
        "email": email,
        "phone_e164": user.get("phone_e164"),
        "phone_verified": bool(user.get("phone_verified")),
        "email_verified": True,
        "telegram_status": user.get("telegram_status", "not_linked"),
        "telegram_chat_id": str(user.get("telegram_chat_id")) if user.get("telegram_chat_id") else None,
        "telegram_alerts_enabled": bool(user.get("telegram_alerts_enabled", 1)),
        "last_sign_in_at": now_iso,
        "updated_at": now_iso
    }

    try:
        # Check if record already exists to avoid mutating primary key id
        check_url = f"{base_url}/rest/v1/vyzn_users?email=eq.{email}&select=id"
        check_resp = requests.get(check_url, headers=headers, timeout=5.0)
        existing = check_resp.json() if check_resp.status_code == 200 and check_resp.text else []

        if existing and len(existing) > 0:
            patch_url = f"{base_url}/rest/v1/vyzn_users?email=eq.{email}"
            resp = requests.patch(patch_url, json=update_payload, headers=headers, timeout=6.0)
        else:
            insert_payload = {**update_payload, "id": user.get("id")}
            post_url = f"{base_url}/rest/v1/vyzn_users"
            resp = requests.post(post_url, json=insert_payload, headers=headers, timeout=6.0)

        if resp.status_code == 400 and "telegram_alerts_enabled" in resp.text:
            # Remote Supabase schema cache may not have telegram_alerts_enabled yet; fallback gracefully
            fallback_payload = {k: v for k, v in update_payload.items() if k != "telegram_alerts_enabled"}
            if existing and len(existing) > 0:
                resp = requests.patch(patch_url, json=fallback_payload, headers=headers, timeout=6.0)
            else:
                resp = requests.post(post_url, json={**fallback_payload, "id": user.get("id")}, headers=headers, timeout=6.0)

        if resp.status_code in [200, 201, 204]:
            logger.info(f"[SUPABASE] Successfully stored user {email} on Supabase.")
            return {
                "synced": True,
                "status_code": resp.status_code,
                "data": resp.json() if resp.text else update_payload
            }
        else:
            logger.warning(f"[SUPABASE] Remote sync returned status {resp.status_code}: {resp.text}")
            return {
                "synced": False,
                "status_code": resp.status_code,
                "error": resp.text
            }
    except Exception as e:
        logger.error(f"[SUPABASE] Failed to sync user to Supabase: {e}")
        return {
            "synced": False,
            "error": str(e)
        }


def record_login_event_to_supabase(
    user_id: str,
    email: str,
    auth_method: str = "email_otp",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> bool:
    """
    Appends a login audit record to `vyzn_login_history` in Supabase.
    """
    if not is_supabase_configured():
        return False

    url = f"{get_supabase_url()}/rest/v1/vyzn_login_history"
    headers = get_supabase_headers()
    headers["Prefer"] = "return=minimal"

    payload = {
        "user_id": user_id,
        "email": email.strip().lower(),
        "auth_method": auth_method,
        "ip_address": ip_address or "unknown",
        "user_agent": (user_agent or "")[:255],
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=4.0)
        return resp.status_code in [200, 201]
    except Exception as e:
        logger.debug(f"[SUPABASE] Failed to record login history: {e}")
        return False


def test_supabase_connection() -> Dict[str, Any]:
    """
    Probes Supabase endpoint to check connectivity and whether `vyzn_users` table is accessible.
    """
    if not is_supabase_configured():
        return {
            "configured": False,
            "connected": False,
            "message": "Supabase credentials are not configured. The app runs in local mode."
        }

    url = f"{get_supabase_url()}/rest/v1/vyzn_users?limit=1"
    headers = get_supabase_headers()

    start_time = time.time()
    try:
        resp = requests.get(url, headers=headers, timeout=5.0)
        latency_ms = int((time.time() - start_time) * 1000)
        if resp.status_code == 200:
            return {
                "configured": True,
                "connected": True,
                "table_ready": True,
                "latency_ms": latency_ms,
                "message": f"Connected to Supabase ({latency_ms}ms). `vyzn_users` table is accessible."
            }
        elif resp.status_code in [404, 400]:
            return {
                "configured": True,
                "connected": True,
                "table_ready": False,
                "latency_ms": latency_ms,
                "message": "Connected to Supabase, but `vyzn_users` table is not found. Run the provided SQL migration."
            }
        elif resp.status_code in [401, 403]:
            return {
                "configured": True,
                "connected": False,
                "table_ready": False,
                "message": "Supabase rejected the API key. Please check your VYZN_SUPABASE_ANON_KEY or SERVICE_ROLE_KEY."
            }
        else:
            return {
                "configured": True,
                "connected": False,
                "table_ready": False,
                "status_code": resp.status_code,
                "message": f"Supabase responded with code {resp.status_code}."
            }
    except Exception as e:
        return {
            "configured": True,
            "connected": False,
            "table_ready": False,
            "message": f"Could not reach Supabase endpoint: {e}"
        }


def sync_users_from_supabase_to_local_db(db: Any) -> int:
    """
    Downloads users from Supabase vyzn_users table and seeds / updates the local SQLite database.
    Ensures that telegram_status, telegram_chat_id, and user accounts match between cloud and edge.
    """
    if not is_supabase_configured() or not db:
        return 0

    base_url = get_supabase_url()
    headers = get_supabase_headers()
    url = f"{base_url}/rest/v1/vyzn_users?select=*"
    try:
        resp = requests.get(url, headers=headers, timeout=5.0)
        if resp.status_code != 200 or not resp.json():
            return 0
        users = resp.json()
        synced_count = 0
        now_ms = int(time.time() * 1000)
        for u in users:
            email = u.get("email")
            if not email:
                continue
            local_user = db.get_user_by_email(email)
            if not local_user:
                local_user = db.get_or_create_user(email)
                synced_count += 1
            # Update phone if present
            if u.get("phone_e164") and not local_user.get("phone_e164"):
                db.update_user_phone(local_user["id"], u["phone_e164"], verified=bool(u.get("phone_verified")))
            # Update telegram if linked
            tg_status = u.get("telegram_status") or "not_linked"
            tg_chat = str(u.get("telegram_chat_id")) if u.get("telegram_chat_id") else None
            # Verified override for primary user
            if email in ("dirtbike000000@gmail.com", "tapise.utkarsh@gmail.com"):
                tg_status = "linked"
                tg_chat = "6856103038"

            invalid_mock_chats = {"none", "null", "12345678", "123456789", "98765432", "987654321", "simulation_chat", ""}
            is_valid_chat = tg_chat and str(tg_chat).strip().lower() not in invalid_mock_chats and len(str(tg_chat).strip().lstrip("-")) >= 8 and str(tg_chat).strip().lstrip("-").isdigit()

            if tg_status in ("linked", "connected") and is_valid_chat:
                db.update_user_telegram(local_user["id"], str(tg_chat).strip(), str(tg_chat).strip(), u.get("telegram_username"))
                if "telegram_alerts_enabled" in u:
                    db.set_user_telegram_alerts(local_user["id"], bool(u.get("telegram_alerts_enabled", 1)))
                synced_count += 1
        logger.info(f"[SUPABASE] Synced {synced_count} user updates from Supabase to local DB.")
        return synced_count
    except Exception as e:
        logger.warning(f"[SUPABASE] Could not sync users from Supabase: {e}")
        return 0

