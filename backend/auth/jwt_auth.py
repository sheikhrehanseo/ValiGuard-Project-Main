"""
JWT issuing/verification and the @require_auth decorator.

Tokens are HS256-signed, carry the wallet address as `sub`, and expire after
JWT_TTL_SECONDS (24h by default). The signing secret comes from the
VALIGUARD_JWT_SECRET env var; a per-process random secret is used in
development so tokens never silently validate across restarts.
"""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, Optional

import jwt
from flask import g, jsonify, request

logger = logging.getLogger(__name__)

JWT_TTL_SECONDS = 24 * 60 * 60  # 24 hours
JWT_ISSUER = "valiguard-api"
JWT_ALGORITHM = "HS256"

_jwt_secret: Optional[str] = None


def get_jwt_secret() -> str:
    """Resolve the JWT signing secret (env override, else per-process random)."""
    global _jwt_secret
    if _jwt_secret is None:
        secret = os.getenv("VALIGUARD_JWT_SECRET", "")
        if secret:
            _jwt_secret = secret
        else:
            # Dev fallback: random per-process secret. Tokens are invalidated
            # on restart — production must set VALIGUARD_JWT_SECRET.
            _jwt_secret = secrets.token_hex(32)
            logger.warning(
                "VALIGUARD_JWT_SECRET not set; using a random per-process secret "
                "(tokens invalidate on restart — set the env var in production)"
            )
    return _jwt_secret


def create_token(address: str) -> str:
    """Issue a JWT for a verified wallet address (24h expiry)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": address.lower(),
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=JWT_TTL_SECONDS),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def decode_token(token: str) -> Optional[Dict]:
    """
    Decode and verify a JWT.

    Returns:
        Payload dict if valid, else None.
    """
    try:
        return jwt.decode(
            token, get_jwt_secret(), algorithms=["HS256"], issuer=JWT_ISSUER
        )
    except jwt.ExpiredSignatureError:
        logger.info("Rejected expired JWT")
        return None
    except jwt.InvalidTokenError as e:
        logger.info("Rejected invalid JWT: %s", e)
        return None


def extract_bearer_token() -> Optional[str]:
    """Pull the Bearer token from the Authorization header, if present."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        token = header.split(" ", 1)[1].strip()
        return token or None
    return None


def require_auth(f):
    """
    Decorator enforcing JWT auth on secure telemetry endpoints.

    On success, injects `g.wallet_address` (lowercase) for the handler.
    Returns 401 with a machine-readable code otherwise.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = extract_bearer_token()
        if not token:
            return jsonify({
                "success": False,
                "error": "Missing bearer token",
                "code": "AUTH_REQUIRED",
            }), 401
        payload = decode_token(token)
        if payload is None:
            return jsonify({
                "success": False,
                "error": "Invalid or expired token",
                "code": "AUTH_INVALID_TOKEN",
            }), 401
        # Attach identity for the wrapped handler.
        g.wallet_address = payload.get("sub")
        return f(*args, **kwargs)

    return decorated_function
