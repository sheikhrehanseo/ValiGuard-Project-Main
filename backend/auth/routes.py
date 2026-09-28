"""
/api/v1/auth/* Flask routes implementing the Web3 login flow (UC-01).

Flow (matches the Phase 1 documentation sequence diagram, section 4.10):

1. POST /api/v1/auth/request-nonce  {address}
       -> {nonce, message, expires_in}
2. Wallet signs `message` with personal_sign (MetaMask / ethers.js).
3. POST /api/v1/auth/verify  {address, nonce, signature}
       -> backend re-builds the signed message server-side, recovers the
          signer from the signature, consumes the nonce, issues a JWT.
       -> {token, token_type, expires_in, address}
4. GET /api/v1/auth/me (Bearer token) -> authenticated identity.
"""

import logging
import re

from eth_account import Account
from eth_account.messages import encode_defunct
from flask import jsonify, request

from auth.jwt_auth import (
    JWT_TTL_SECONDS,
    create_token,
    decode_token,
    extract_bearer_token,
)
from auth.nonce_store import NonceStore, build_sign_message

logger = logging.getLogger(__name__)

# Module-level store shared by all requests in this process.
nonce_store = NonceStore()

_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _error(message: str, code: str, status: int):
    return jsonify({"success": False, "error": message, "code": code}), status


def verify_signature(address: str, expected_message: str, signature: str) -> bool:
    """
    Recover the signer from an EIP-191 personal_sign signature and compare
    against the claimed address (case-insensitive).
    """
    try:
        recovered = Account.recover_message(
            encode_defunct(text=expected_message), signature=signature
        )
    except Exception as e:  # malformed signature / encoding
        logger.info("Signature recovery failed for %s: %s", address, e)
        return False
    return str(recovered).lower() == address.lower()


def register_auth_routes(app):
    """Register the /api/v1/auth/* routes on the Flask app."""

    @app.route("/api/v1/auth/request-nonce", methods=["POST"])
    def auth_request_nonce():
        """Step 1: issue a single-use nonce + the message to sign."""
        body = request.get_json(silent=True) or {}
        address = (body.get("address") or "").strip()
        if not _ADDRESS_PATTERN.match(address):
            return _error("Invalid wallet address", "INVALID_ADDRESS", 400)

        nonce, message = nonce_store.issue(address)
        return jsonify({
            "success": True,
            "data": {
                "nonce": nonce,
                "message": message,
                "expires_in": nonce_store.ttl_seconds,
            },
        }), 200

    @app.route("/api/v1/auth/verify", methods=["POST"])
    def auth_verify():
        body = request.get_json(silent=True) or {}
        address = (body.get("address") or "").strip()
        signature = (body.get("signature") or "").strip()
        nonce = (body.get("nonce") or "").strip()

        if not _ADDRESS_PATTERN.match(address):
            return _error("Invalid wallet address", "INVALID_ADDRESS", 400)
        if not signature or not nonce:
            return _error("signature and nonce are required", "INVALID_REQUEST", 400)

        # The signed message must be the exact one we issued for this nonce —
        # it's stored server-side at issue time so the client can't inject text.
        # consume() is single-use and returns the stored message, or None.
        expected_message = nonce_store.consume(address, nonce)
        if expected_message is None:
            return _error(
                "Nonce is invalid or expired — request a new one",
                "NONCE_INVALID",
                401,
            )

        if not verify_signature(address, expected_message, signature):
            return _error("Signature verification failed", "SIGNATURE_INVALID", 401)

        token = create_token(address)
        return jsonify({
            "success": True,
            "data": {
                "token": token,
                "token_type": "Bearer",
                "expires_in": JWT_TTL_SECONDS,
                "address": address.lower(),
            },
        }), 200

    @app.route("/api/v1/auth/me", methods=["GET"])
    def auth_me():
        token = extract_bearer_token()
        payload = decode_token(token) if token else None
        if payload is None:
            return _error("Invalid or expired token", "AUTH_INVALID_TOKEN", 401)
        return jsonify({
            "success": True,
            "data": {"address": payload.get("sub"), "expires_at": payload.get("exp")},
        }), 200

    return app
