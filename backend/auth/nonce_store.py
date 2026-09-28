"""
In-memory nonce store for the Web3 authentication flow.

Each wallet address is issued a single-use nonce that expires after
NONCE_TTL_SECONDS. The nonce must be presented (and signed) at
/auth/verify; it is consumed on successful verification or expiry.
Thread-safe: the ingestion worker and Flask handlers run in separate
threads but share the module-level store via app.py.
"""

import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

NONCE_TTL_SECONDS = 300  # 5 minutes to sign and submit


class NonceStore:
    """Single-use nonce store with expiry, keyed by wallet address."""

    def __init__(self, ttl_seconds: int = NONCE_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        # address -> (nonce, expires_at, message) — the message is stored
        # verbatim because it embeds an "Issued At" timestamp that must be
        # byte-identical between issue and verification.
        self._nonces: Dict[str, Tuple[str, float, str]] = {}
        self._lock = threading.Lock()

    def issue(self, address: str) -> Tuple[str, str]:
        """
        Issue a fresh nonce + the exact message the wallet must sign.

        Args:
            address: Checksummed/case-insensitive wallet address.

        Returns:
            (nonce, message_to_sign)
        """
        self._cleanup()
        nonce = secrets.token_hex(16)
        normalized = address.lower()
        message = build_sign_message(address, nonce)
        with self._lock:
            self._nonces[normalized] = (nonce, time.time() + self.ttl_seconds, message)
        return nonce, message

    def consume(self, address: str, nonce: str) -> Optional[str]:
        """
        Validate and consume the nonce for an address (single use).

        Returns:
            The exact message that was issued for this nonce if valid,
            else None (unknown / mismatched / expired).
        """
        normalized = address.lower()
        now = time.time()
        with self._lock:
            entry = self._nonces.get(normalized)
            if entry is None:
                return None
            stored_nonce, expires_at, message = entry
            if now > expires_at or not secrets.compare_digest(stored_nonce, nonce or ""):
                # Expired or mismatched: drop it so it can't be replayed.
                self._nonces.pop(normalized, None)
                return None
            # Single use — delete on success.
            del self._nonces[normalized]
            return message

    def _cleanup(self) -> None:
        """Drop expired nonces."""
        now = time.time()
        with self._lock:
            expired = [
                addr for addr, (_, exp, _) in self._nonces.items() if exp <= now
            ]
            for addr in expired:
                del self._nonces[addr]


def build_sign_message(address: str, nonce: str) -> str:
    """Build the deterministic sign-in message (EIP-191 personal_sign payload)."""
    return (
        "ValiGuard AI wants you to sign in with your Ethereum account:\n"
        f"{address}\n"
        "\n"
        "This signature authenticates you to the ValiGuard bridge telemetry API.\n"
        "\n"
        "URI: https://valiguard.local\n"
        "Version: 1\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {datetime.now(timezone.utc).isoformat()}"
    )
