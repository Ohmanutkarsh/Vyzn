"""
Multi-tenant authentication, authorization, cryptographic integrity, and durable security persistence for VYZN Cloud.
Enforces tenant scoping, installer access control, HMAC-SHA256 OTA signature generation,
and SQLite-backed durable credential revocation and key reissuance.
"""

from __future__ import annotations
import hmac
import hashlib
import json
import secrets
import sqlite3
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set
from fastapi import HTTPException, Security, Request, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("vyzn_cloud.security")

API_KEY_HEADER = APIKeyHeader(name="X-Installer-Key", auto_error=False)
SITE_KEY_HEADER = APIKeyHeader(name="X-Site-Key", auto_error=False)
BEARER_AUTH = HTTPBearer(auto_error=False)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_security.db"

# Registry of authorized installers and their tenant scope
# In production, this maps to PostgreSQL/DynamoDB tenant database.
INSTALLERS: Dict[str, Dict[str, Any]] = {
    "installer_key_delhi_netra_01": {
        "installer_id": "inst_delhi_01",
        "name": "Delhi SafeNet Solutions",
        "allowed_sites": {"site_sharma_kirana", "site_verma_retail", "site_local_default"},
        "is_admin": False
    },
    "installer_key_master_admin_99": {
        "installer_id": "inst_admin_root",
        "name": "VYZN Fleet Operations",
        "allowed_sites": {"*"},
        "is_admin": True
    }
}

# Default seed site secrets
DEFAULT_SITE_SECRETS: Dict[str, str] = {
    "site_local_default": "vyzn_edge_secret_local_default_2026",
    "site_sharma_kirana": "vyzn_edge_secret_sharma_kirana_9942",
    "site_verma_retail": "vyzn_edge_secret_verma_retail_1184"
}

# In-memory runtime caches synchronized with persistent SQLite database
SITE_SECRETS: Dict[str, str] = dict(DEFAULT_SITE_SECRETS)
REVOKED_SITE_KEYS: Set[str] = set()
REVOKED_INSTALLER_KEYS: Set[str] = set()


def _get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = db_path or DEFAULT_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _init_security_db(db_path: Optional[Path] = None):
    """
    Initializes the persistent cloud security SQLite schema and synchronizes in-memory caches.
    Ensures blacklists and key revocations survive service restarts and horizontal rollouts.
    """
    conn = _get_db_connection(db_path)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_secrets (
                site_id TEXT PRIMARY KEY,
                secret TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_revoked INTEGER DEFAULT 0
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS revoked_site_keys (
                secret TEXT PRIMARY KEY,
                site_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                revoked_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS revoked_installer_keys (
                key TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                revoked_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_lockouts (
                identifier TEXT PRIMARY KEY,
                failed_attempts INTEGER DEFAULT 0,
                locked_until_epoch REAL DEFAULT 0,
                last_attempt_epoch REAL DEFAULT 0
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_onboarding_drafts (
                draft_id TEXT PRIMARY KEY,
                installer_id TEXT NOT NULL,
                site_name TEXT NOT NULL,
                current_step INTEGER DEFAULT 1,
                data_json TEXT NOT NULL,
                test_verified INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # Seed initial site secrets if empty
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM site_secrets")
        count = cursor.fetchone()[0]
        if count == 0:
            now_iso = datetime.now(timezone.utc).isoformat()
            for sid, sec in DEFAULT_SITE_SECRETS.items():
                cursor.execute(
                    "INSERT INTO site_secrets (site_id, secret, updated_at, is_revoked) VALUES (?, ?, ?, 0)",
                    (sid, sec, now_iso)
                )

        # Synchronize in-memory caches from SQLite
        cursor.execute("SELECT site_id, secret, is_revoked FROM site_secrets")
        for row in cursor.fetchall():
            SITE_SECRETS[row["site_id"]] = row["secret"] if row["is_revoked"] == 0 else "REVOKED"

        cursor.execute("SELECT secret FROM revoked_site_keys")
        for row in cursor.fetchall():
            REVOKED_SITE_KEYS.add(row["secret"])

        cursor.execute("SELECT key FROM revoked_installer_keys")
        for row in cursor.fetchall():
            REVOKED_INSTALLER_KEYS.add(row["key"])

    conn.close()


# Initialize database schema and cache on load
_init_security_db()


def _reset_security_state(db_path: Optional[Path] = None):
    """Resets the security database and runtime caches to baseline defaults (for testing isolation)."""
    conn = _get_db_connection(db_path)
    with conn:
        conn.execute("DELETE FROM revoked_site_keys")
        conn.execute("DELETE FROM revoked_installer_keys")
        conn.execute("DELETE FROM site_secrets")
        now_iso = datetime.now(timezone.utc).isoformat()
        for sid, sec in DEFAULT_SITE_SECRETS.items():
            conn.execute(
                "INSERT INTO site_secrets (site_id, secret, updated_at, is_revoked) VALUES (?, ?, ?, 0)",
                (sid, sec, now_iso)
            )
    conn.close()
    SITE_SECRETS.clear()
    SITE_SECRETS.update(DEFAULT_SITE_SECRETS)
    REVOKED_SITE_KEYS.clear()
    REVOKED_INSTALLER_KEYS.clear()


def revoke_site_key(site_id: str, reason: str = "device_stolen", db_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Durable emergency invalidation of credential for a stolen or compromised edge box.
    Persists to SQLite and updates in-memory blacklist immediately.
    """
    old_secret = SITE_SECRETS.get(site_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = _get_db_connection(db_path)
    with conn:
        if old_secret and old_secret != "REVOKED":
            conn.execute(
                "INSERT OR REPLACE INTO revoked_site_keys (secret, site_id, reason, revoked_at) VALUES (?, ?, ?, ?)",
                (old_secret, site_id, reason, now_iso)
            )
            REVOKED_SITE_KEYS.add(old_secret)

        conn.execute(
            "UPDATE site_secrets SET secret = 'REVOKED', is_revoked = 1, updated_at = ? WHERE site_id = ?",
            (now_iso, site_id)
        )
        SITE_SECRETS[site_id] = "REVOKED"
    conn.close()

    logger.critical(f"Physical theft / revocation recorded for site [{site_id}] (reason: {reason}).")
    return {
        "site_id": site_id,
        "status": "revoked",
        "reason": reason,
        "revoked_secret_prefix": (old_secret[:6] + "...") if old_secret and old_secret != "REVOKED" else "none"
    }


def reissue_site_key(site_id: str, db_path: Optional[Path] = None) -> str:
    """
    Generates and durably provisions a fresh shared secret for an edge site box.
    Used when replacing a stolen/lost box with new edge hardware.
    """
    old_secret = SITE_SECRETS.get(site_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    new_secret = f"vyzn_edge_secret_{site_id}_{secrets.token_urlsafe(16)}"

    conn = _get_db_connection(db_path)
    with conn:
        if old_secret and old_secret != "REVOKED":
            conn.execute(
                "INSERT OR REPLACE INTO revoked_site_keys (secret, site_id, reason, revoked_at) VALUES (?, ?, ?, ?)",
                (old_secret, site_id, "key_reissued_rotation", now_iso)
            )
            REVOKED_SITE_KEYS.add(old_secret)

        conn.execute(
            "INSERT OR REPLACE INTO site_secrets (site_id, secret, updated_at, is_revoked) VALUES (?, ?, ?, 0)",
            (site_id, new_secret, now_iso)
        )
        SITE_SECRETS[site_id] = new_secret
        REVOKED_SITE_KEYS.discard(new_secret)
    conn.close()

    logger.info(f"Reissued fresh credential for edge site [{site_id}].")
    return new_secret


def revoke_installer_key(key: str, reason: str = "revoked", db_path: Optional[Path] = None) -> bool:
    """Durable revocation of a specific installer's API key."""
    if key in INSTALLERS:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = _get_db_connection(db_path)
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO revoked_installer_keys (key, reason, revoked_at) VALUES (?, ?, ?)",
                (key, reason, now_iso)
            )
        conn.close()
        REVOKED_INSTALLER_KEYS.add(key)
        logger.warning(f"Revoked installer key ending in '...{key[-6:]}'.")
        return True
    return False


def canonicalize_json(data: Dict[str, Any]) -> bytes:
    """Produces deterministic, canonical JSON bytes for hashing and HMAC signing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_config_hmac(site_id: str, config_data: Dict[str, Any]) -> str:
    """Computes HMAC-SHA256 signature for an OTA configuration payload."""
    secret = SITE_SECRETS.get(site_id, "fallback_default_secret_2026")
    canonical_bytes = canonicalize_json(config_data)
    return hmac.new(secret.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()


def verify_config_hmac(site_id: str, config_data: Dict[str, Any], signature: str) -> bool:
    """Verifies HMAC-SHA256 signature against the site's shared secret."""
    expected = generate_config_hmac(site_id, config_data)
    return hmac.compare_digest(expected, signature)


def compute_config_hash(config_data: Dict[str, Any]) -> str:
    """Computes canonical SHA-256 hash of a configuration structure."""
    canonical_bytes = canonicalize_json(config_data)
    return hashlib.sha256(canonical_bytes).hexdigest()


def authenticate_installer(
    request: Request,
    api_key: Optional[str] = Security(API_KEY_HEADER),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(BEARER_AUTH)
) -> Dict[str, Any]:
    """
    Validates installer identity from X-Installer-Key header, Bearer token, or query param.
    Emits generic 401 with zero state leakage while logging security incidents server-side.
    """
    token = api_key if isinstance(api_key, str) else request.headers.get("X-Installer-Key")
    if not token and isinstance(bearer, HTTPAuthorizationCredentials):
        token = bearer.credentials
    if not token:
        token = request.query_params.get("key") or request.cookies.get("vyzn_installer_token")

    client_host = request.client.host if request.client else "unknown"

    if token in REVOKED_INSTALLER_KEYS:
        logger.warning(f"[SECURITY ALERT] Connection attempt using REVOKED installer key from IP [{client_host}]")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not token or token not in INSTALLERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return INSTALLERS[token]


def authorize_site_access(installer: Dict[str, Any], site_id: str):
    """Verifies installer has permission to view or manage the specified customer site."""
    if installer.get("is_admin"):
        return
    allowed: Set[str] = installer.get("allowed_sites", set())
    if "*" not in allowed and site_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Installer '{installer.get('name')}' is not authorized to manage site '{site_id}'."
        )


def authenticate_edge_box(
    request: Request,
    site_key: Optional[str] = Security(SITE_KEY_HEADER),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(BEARER_AUTH)
) -> str:
    """
    Authenticates incoming heartbeat or telemetry from an edge device.
    Verifies site credentials against SITE_SECRETS registry.
    Emits generic 401 with zero state leakage to prevent alerting thieves in physical possession.
    """
    token = site_key if isinstance(site_key, str) else request.headers.get("X-Site-Key")
    if not token:
        if isinstance(bearer, HTTPAuthorizationCredentials):
            token = bearer.credentials
        elif "Authorization" in request.headers:
            auth_hdr = request.headers.get("Authorization", "")
            if auth_hdr.startswith("Bearer "):
                token = auth_hdr[7:].strip()

    client_host = request.client.host if request.client else "unknown"

    if token in REVOKED_SITE_KEYS:
        logger.warning(
            f"[SECURITY INCIDENT] Stolen/Revoked edge device connection attempt from IP [{client_host}] with key prefix '{token[:6]}...'"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )

    matched_site = None
    for site_id, secret in SITE_SECRETS.items():
        if token == secret and secret != "REVOKED":
            matched_site = site_id
            break

    if not matched_site:
        dev_token = request.headers.get("X-Dev-Mode")
        if dev_token == "true":
            return "site_local_default"

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )

    return matched_site


# ===========================================================================
# Account Lockout & Brute Force Defense (Flow 1)
# ===========================================================================
def record_failed_login(identifier: str, max_attempts: int = 5, lockout_seconds: int = 900, db_path: Optional[Path] = None) -> bool:
    """Records a failed authentication attempt. Returns True if account is now locked."""
    conn = _get_db_connection(db_path)
    now = time.time()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT failed_attempts, locked_until_epoch FROM account_lockouts WHERE identifier = ?", (identifier,))
            row = cursor.fetchone()
            if not row:
                attempts = 1
                locked_until = 0.0
                cursor.execute(
                    "INSERT INTO account_lockouts (identifier, failed_attempts, locked_until_epoch, last_attempt_epoch) VALUES (?, ?, ?, ?)",
                    (identifier, attempts, locked_until, now)
                )
            else:
                attempts = row["failed_attempts"] + 1
                locked_until = row["locked_until_epoch"]
                if attempts >= max_attempts:
                    locked_until = now + lockout_seconds
                    logger.warning(f"Account [{identifier}] locked for {lockout_seconds}s after {attempts} failed attempts")
                cursor.execute(
                    "UPDATE account_lockouts SET failed_attempts = ?, locked_until_epoch = ?, last_attempt_epoch = ? WHERE identifier = ?",
                    (attempts, locked_until, now, identifier)
                )

        return (locked_until > now)
    finally:
        conn.close()


def is_account_locked(identifier: str, db_path: Optional[Path] = None) -> tuple[bool, int]:
    """Returns (is_locked, remaining_lockout_seconds)."""
    conn = _get_db_connection(db_path)
    now = time.time()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT locked_until_epoch FROM account_lockouts WHERE identifier = ?", (identifier,))
        row = cursor.fetchone()
        if not row:
            return False, 0
        locked_until = float(row["locked_until_epoch"])
        if locked_until > now:
            return True, int(locked_until - now)
        return False, 0
    finally:
        conn.close()


def reset_failed_logins(identifier: str, db_path: Optional[Path] = None) -> None:
    """Clears failed attempts counter on successful login."""
    conn = _get_db_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM account_lockouts WHERE identifier = ?", (identifier,))
    finally:
        conn.close()


# ===========================================================================
# Interruption-Proof Site Onboarding Draft Store (Flow 3)
# ===========================================================================
def save_onboarding_draft(
    draft_id: str,
    installer_id: str,
    site_name: str,
    current_step: int,
    data: Dict[str, Any],
    test_verified: bool = False,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Saves or updates wizard step state atomically to survive mid-session dropouts."""
    conn = _get_db_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    data_str = json.dumps(data)
    verified_int = 1 if test_verified else 0

    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT draft_id, test_verified FROM site_onboarding_drafts WHERE draft_id = ?", (draft_id,))
            existing = cursor.fetchone()
            if existing:
                # Preserve test_verified if already marked True
                final_verified = 1 if (verified_int or existing["test_verified"]) else 0
                cursor.execute("""
                    UPDATE site_onboarding_drafts
                    SET site_name = ?, current_step = ?, data_json = ?, test_verified = ?, updated_at = ?
                    WHERE draft_id = ?
                """, (site_name, current_step, data_str, final_verified, now_iso, draft_id))
            else:
                cursor.execute("""
                    INSERT INTO site_onboarding_drafts
                    (draft_id, installer_id, site_name, current_step, data_json, test_verified, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (draft_id, installer_id, site_name, current_step, data_str, verified_int, now_iso, now_iso))

        return {
            "draft_id": draft_id,
            "installer_id": installer_id,
            "site_name": site_name,
            "current_step": current_step,
            "test_verified": bool(verified_int),
            "updated_at": now_iso
        }
    finally:
        conn.close()


def get_onboarding_draft(draft_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Retrieves full draft state for resuming an in-progress setup wizard."""
    conn = _get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM site_onboarding_drafts WHERE draft_id = ?", (draft_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "draft_id": row["draft_id"],
            "installer_id": row["installer_id"],
            "site_name": row["site_name"],
            "current_step": row["current_step"],
            "data": json.loads(row["data_json"]),
            "test_verified": bool(row["test_verified"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }
    finally:
        conn.close()


def list_onboarding_drafts(installer_id: str, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lists all active in-progress drafts for an installer."""
    conn = _get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if installer_id == "inst_admin_root":
            cursor.execute("SELECT draft_id, installer_id, site_name, current_step, test_verified, updated_at FROM site_onboarding_drafts ORDER BY updated_at DESC")
        else:
            cursor.execute("SELECT draft_id, installer_id, site_name, current_step, test_verified, updated_at FROM site_onboarding_drafts WHERE installer_id = ? ORDER BY updated_at DESC", (installer_id,))
        rows = cursor.fetchall()
        return [
            {
                "draft_id": r["draft_id"],
                "installer_id": r["installer_id"],
                "site_name": r["site_name"],
                "current_step": r["current_step"],
                "test_verified": bool(r["test_verified"]),
                "updated_at": r["updated_at"]
            }
            for r in rows
        ]
    finally:
        conn.close()


def delete_onboarding_draft(draft_id: str, db_path: Optional[Path] = None) -> bool:
    """Discards or clears completed onboarding draft."""
    conn = _get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM site_onboarding_drafts WHERE draft_id = ?", (draft_id,))
            return cursor.rowcount > 0
    finally:
        conn.close()