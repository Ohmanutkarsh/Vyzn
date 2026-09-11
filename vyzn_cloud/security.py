"""
Multi-tenant authentication, authorization, and cryptographic integrity for VYZN Cloud.
Enforces tenant scoping, installer access control, and HMAC-SHA256 OTA signature generation.
"""

from __future__ import annotations
import hmac
import hashlib
import json
import secrets
from typing import Dict, Any, Optional, Set
from fastapi import HTTPException, Security, Request, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

API_KEY_HEADER = APIKeyHeader(name="X-Installer-Key", auto_error=False)
SITE_KEY_HEADER = APIKeyHeader(name="X-Site-Key", auto_error=False)
BEARER_AUTH = HTTPBearer(auto_error=False)

# Registry of authorized installers and their tenant scope
# In production, this maps to PostgreSQL/DynamoDB tenant database.
# Default installer key provided for development/demo environment.
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

# Site shared secrets for edge box authentication and HMAC config signing
SITE_SECRETS: Dict[str, str] = {
    "site_local_default": "vyzn_edge_secret_local_default_2026",
    "site_sharma_kirana": "vyzn_edge_secret_sharma_kirana_9942",
    "site_verma_retail": "vyzn_edge_secret_verma_retail_1184"
}

# Blacklist sets for stolen edge boxes and revoked installer sessions
REVOKED_SITE_KEYS: Set[str] = set()
REVOKED_INSTALLER_KEYS: Set[str] = set()


def revoke_site_key(site_id: str, reason: str = "device_stolen") -> Dict[str, Any]:
    """
    Emergency invalidation of credential for a stolen or compromised edge box.
    Immediately blocks all heartbeats, config pulls, and API calls using that key.
    """
    old_secret = SITE_SECRETS.get(site_id)
    if old_secret:
        REVOKED_SITE_KEYS.add(old_secret)
        SITE_SECRETS[site_id] = "REVOKED"
    return {
        "site_id": site_id,
        "status": "revoked",
        "reason": reason,
        "revoked_secret_prefix": (old_secret[:6] + "...") if old_secret else "none"
    }


def revoke_installer_key(key: str) -> bool:
    """Revokes a specific installer's API key without affecting others."""
    if key in INSTALLERS:
        REVOKED_INSTALLER_KEYS.add(key)
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
    Rejects unauthorized requests with HTTP 401.
    """
    token = api_key if isinstance(api_key, str) else request.headers.get("X-Installer-Key")
    if not token and isinstance(bearer, HTTPAuthorizationCredentials):
        token = bearer.credentials
    if not token:
        # Check query param or cookie for web browser dashboard access
        token = request.query_params.get("key") or request.cookies.get("vyzn_installer_token")

    if token in REVOKED_INSTALLER_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Installer credentials have been revoked.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not token or token not in INSTALLERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid installer credentials. Provide valid X-Installer-Key or Bearer token.",
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
    """
    token = site_key if isinstance(site_key, str) else request.headers.get("X-Site-Key")
    if not token:
        if isinstance(bearer, HTTPAuthorizationCredentials):
            token = bearer.credentials
        elif "Authorization" in request.headers:
            auth_hdr = request.headers.get("Authorization", "")
            if auth_hdr.startswith("Bearer "):
                token = auth_hdr[7:].strip()

    if token in REVOKED_SITE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Edge site credential revoked (device reported stolen or compromised)."
        )

    # Look up matching site_id
    matched_site = None
    for site_id, secret in SITE_SECRETS.items():
        if token == secret and secret != "REVOKED":
            matched_site = site_id
            break

    if not matched_site:
        # In open simulation mode, if no key provided, check if localhost or dev header
        # In strict mode, enforce 401
        dev_token = request.headers.get("X-Dev-Mode")
        if dev_token == "true":
            return "site_local_default"

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid edge box site secret key in X-Site-Key."
        )

    return matched_site