"""
Tests for the Web3 authentication flow (UC-01): nonce -> signature -> JWT.

Covers: guarded endpoints reject anonymous access, the happy path issues a
valid JWT, nonce replay is rejected, wrong-signer signatures are rejected,
and JWT expiry/expired tokens are rejected.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from eth_account import Account
from eth_account.messages import encode_defunct


@pytest.fixture(scope="module")
def client():
    # app.py imports `backend.qie_node_manager`, so the project root must be
    # importable as well as the backend/ dir itself.
    root = Path(__file__).parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import app as flask_app_module  # noqa: F401 — module import wires everything
    return flask_app_module.app.test_client()


def _hex_sig(signed) -> str:
    sig = signed.signature.hex()
    return sig if sig.startswith("0x") else f"0x{sig}"


def _login(client, wallet: Account) -> str:
    """Run the full nonce -> sign -> verify flow, return the JWT."""
    r = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
    assert r.status_code == 200
    data = r.get_json()["data"]
    signed = wallet.sign_message(encode_defunct(text=data["message"]))
    r = client.post("/api/v1/auth/verify", json={
        "address": wallet.address,
        "nonce": data["nonce"],
        "signature": _hex_sig(signed),
    })
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["token"]


class TestGuardedEndpoints:
    """Secure telemetry endpoints must require a Bearer token."""

    @pytest.mark.parametrize("path", [
        "/api/v1/bridge/history",
        "/api/v1/analytics/daily-stats",
        "/api/v1/analytics/model-accuracy",
        "/api/v1/analytics/validator-stats",
    ])
    def test_rejects_missing_token(self, client, path):
        r = client.get(path)
        assert r.status_code == 401
        assert r.get_json()["code"] == "AUTH_REQUIRED"

    def test_rejects_invalid_token(self, client):
        r = client.get("/api/v1/analytics/daily-stats",
                       headers={"Authorization": "Bearer not.a.jwt"})
        assert r.status_code == 401
        assert r.get_json()["code"] == "AUTH_INVALID_TOKEN"


class TestNonceEndpoint:
    def test_rejects_invalid_address(self, client):
        r = client.post("/api/v1/auth/request-nonce", json={"address": "0x123"})
        assert r.status_code == 400
        assert r.get_json()["code"] == "INVALID_ADDRESS"

    def test_issues_nonce_and_message(self, client):
        wallet = Account.create()
        r = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
        data = r.get_json()["data"]
        assert data["nonce"]
        assert wallet.address in data["message"]
        assert data["expires_in"] > 0

    def test_nonce_is_single_use_per_address(self, client):
        """A second request-nonce invalidates the first outstanding nonce."""
        wallet = Account.create()
        r1 = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
        r2 = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
        assert r1.get_json()["data"]["nonce"] != r2.get_json()["data"]["nonce"]


class TestVerifyAndJwt:
    def test_happy_path_issues_jwt(self, client):
        wallet = Account.create()
        token = _login(client, wallet)
        assert token.count(".") == 2  # header.payload.signature

        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.get_json()["data"]["address"] == wallet.address.lower()

    def test_grants_access_to_guarded_endpoint(self, client):
        wallet = Account.create()
        token = _login(client, wallet)
        r = client.get("/api/v1/bridge/history",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_nonce_replay_rejected(self, client):
        wallet = Account.create()
        r = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
        data = r.get_json()["data"]
        signed = wallet.sign_message(encode_defunct(text=data["message"]))
        body = {"address": wallet.address, "nonce": data["nonce"],
                "signature": _hex_sig(signed)}

        assert client.post("/api/v1/auth/verify", json=body).status_code == 200
        # Second use of the same nonce must fail
        r = client.post("/api/v1/auth/verify", json=body)
        assert r.status_code == 401
        assert r.get_json()["code"] == "NONCE_INVALID"

    def test_wrong_signer_rejected(self, client):
        wallet = Account.create()
        impostor = Account.create()
        r = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
        data = r.get_json()["data"]
        signed = impostor.sign_message(encode_defunct(text=data["message"]))
        r = client.post("/api/v1/auth/verify", json={
            "address": wallet.address,
            "nonce": data["nonce"],
            "signature": _hex_sig(signed),
        })
        assert r.status_code == 401
        assert r.get_json()["code"] == "SIGNATURE_INVALID"

    def test_expired_nonce_rejected(self, client):
        from auth.routes import nonce_store as routes_store

        wallet = Account.create()
        r = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
        data = r.get_json()["data"]
        # Age the stored nonce past its TTL.
        key = wallet.address.lower()
        nonce, _, message = routes_store._nonces[key]
        routes_store._nonces[key] = (nonce, time.time() - 1, message)

        signed = wallet.sign_message(encode_defunct(text=data["message"]))
        r = client.post("/api/v1/auth/verify", json={
            "address": wallet.address,
            "nonce": data["nonce"],
            "signature": _hex_sig(signed),
        })
        assert r.status_code == 401

    def test_jwt_expired_rejected(self, client):
        from auth import jwt_auth

        token = jwt_auth_create_token_expired()
        r = client.get("/api/v1/analytics/daily-stats",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


def jwt_auth_create_token_expired() -> str:
    """Create a token that expired 1 minute ago (uses the real secret)."""
    import jwt
    from datetime import datetime, timedelta, timezone
    from auth.jwt_auth import get_jwt_secret, JWT_ISSUER

    now = datetime.now(timezone.utc)
    payload = {
        "sub": "0xabc0000000000000000000000000000000000000",
        "iss": JWT_ISSUER,
        "iat": now - timedelta(minutes=2),
        "exp": now - timedelta(minutes=1),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")
