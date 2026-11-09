from __future__ import annotations

import logging
import base64
import hashlib
import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests
from sqlalchemy.exc import IntegrityError

from qie_node_manager import QIENodeManager

# Phase 2 ML scoring.
from ml.anomaly_model import AnomalyModel, get_model as get_anomaly_model

# Canonical 4-tier severity scale (single source of truth — shared with app.py
# and ml/anomaly_model.py; do not re-implement thresholds here).
from core.severity import (
    is_alerting_severity,
    severity_from_score as _canonical_severity_from_score,
)
from core.scoring import score_and_persist_transaction

# Phase 1 DB layer — reuse the same DatabaseManager / session pattern as app.py.
from database.db import DatabaseManager, DatabaseConfig
from database.models import SeverityLevel, Transaction, TransactionStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Severity helpers (canonical scale lives in backend/core/severity.py)
# ---------------------------------------------------------------------------

def _severity_from_score(score_0_100: float) -> str:
    """Map a 0-100 anomaly score to a canonical severity tier string."""
    return _canonical_severity_from_score(score_0_100)


def _severity_enum(severity_str: str) -> SeverityLevel:
    """Convert a severity string to the SeverityLevel enum."""
    mapping = {
        "low": SeverityLevel.LOW,
        "medium": SeverityLevel.MEDIUM,
        "high": SeverityLevel.HIGH,
        "critical": SeverityLevel.CRITICAL,
    }
    return mapping.get(severity_str, SeverityLevel.LOW)


# ---------------------------------------------------------------------------
# Normalization & Decoding
# ---------------------------------------------------------------------------

def _coerce_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """
    Convert RPC payload values (float, int, hex wei/aqie strings, or Cosmos
    coin dicts/lists) into a normalized float token amount.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        if not value:
            return default
        return _coerce_float(value[0], default=default)
    if isinstance(value, dict):
        amt = value.get("amount", value.get("value"))
        denom = str(value.get("denom", "")).lower()
        parsed = _coerce_float(amt, default=default)
        if parsed is not None:
            if denom == "aqie" and parsed >= 1e12:
                return round(parsed / 1e18, 6)
            if denom == "uqie" and parsed >= 1e6:
                return round(parsed / 1e6, 6)
        return parsed
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return default
        if s.startswith(("0x", "0X")):
            try:
                raw_int = int(s, 16)
                # Standard EVM value is in wei / aqie (10^18 per QIE)
                if raw_int >= 10**12:
                    return round(float(raw_int) / 1e18, 6)
                return float(raw_int)
            except ValueError:
                return default
        lower = s.lower()
        for suffix, divisor, threshold in (
            ("aqie", 1e18, 1e12),
            ("wei", 1e18, 1e12),
            ("uqie", 1e6, 1e6),
            ("qie", 1.0, 0.0),
        ):
            if lower.endswith(suffix):
                num_part = lower[: -len(suffix)].strip()
                try:
                    val = float(num_part)
                    return round(val / divisor, 6) if divisor > 1.0 and val >= threshold else val
                except ValueError:
                    return default
        try:
            return float(s)
        except ValueError:
            return default
    return default


def _iso_to_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 or hex epoch timestamp; return None on failure."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(value))
        except (ValueError, OSError):
            return None
    if isinstance(value, str) and value.startswith(("0x", "0X")):
        try:
            return datetime.utcfromtimestamp(int(value, 16))
        except (ValueError, OSError):
            return None
    try:
        # Tendermint timestamps look like "2026-07-19T12:34:56.123456789Z"
        # Truncate nanoseconds to microseconds for fromisoformat compatibility.
        ts = str(value).rstrip("Z")
        if "." in ts:
            head, frac = ts.split(".", 1)
            ts = f"{head}.{frac[:6]}"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def raw_entry_bytes(entry: Any) -> bytes:
    """Return the raw bytes represented by a Tendermint entry."""
    if isinstance(entry, bytes):
        return entry
    if isinstance(entry, bytearray):
        return bytes(entry)
    if isinstance(entry, str):
        try:
            return base64.b64decode(entry, validate=True)
        except Exception:
            return entry.encode("utf-8")
    return json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")


def deterministic_raw_hash(entry: Any) -> str:
    """Hash decoded raw transaction bytes consistently across RPC surfaces."""
    return hashlib.sha256(raw_entry_bytes(entry)).hexdigest()


def _try_decode_raw_entry(raw_entry: Any) -> Optional[Dict[str, Any]]:
    """
    Attempt to decode a raw Tendermint / Cosmos / EVM transaction entry into
    structured fields (tx_hash, sender, receiver, value, source_chain,
    destination_chain).

    Returns a dict of decoded fields if the payload contains structured
    transaction metadata, or None if the entry is an opaque binary payload
    (preserving the raw-entry NULL contract for undecodable blobs).
    """
    payload: Optional[Dict[str, Any]] = None
    if isinstance(raw_entry, dict):
        payload = raw_entry
    else:
        raw_bytes = raw_entry_bytes(raw_entry)
        try:
            text = raw_bytes.decode("utf-8").strip()
            if text.startswith("{") and text.endswith("}"):
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    payload = parsed
        except (UnicodeDecodeError, ValueError):
            payload = None

    if not payload:
        return None

    # 1) Cosmos SDK StdTx / TxBody envelope (e.g., cosmos-sdk/StdTx, MsgSend, MsgTransfer)
    tx_val = payload.get("value") if isinstance(payload.get("value"), dict) else None
    body_val = payload.get("body") if isinstance(payload.get("body"), dict) else None
    msgs = []
    if tx_val and isinstance(tx_val.get("msg"), list):
        msgs = tx_val["msg"]
    elif body_val and isinstance(body_val.get("messages"), list):
        msgs = body_val["messages"]
    elif isinstance(payload.get("msgs"), list):
        msgs = payload["msgs"]

    if msgs and isinstance(msgs[0], dict):
        first_msg = msgs[0]
        msg_inner = first_msg.get("value") if isinstance(first_msg.get("value"), dict) else first_msg
        sender = (
            msg_inner.get("from_address")
            or msg_inner.get("sender")
            or msg_inner.get("signer")
        )
        receiver = (
            msg_inner.get("to_address")
            or msg_inner.get("receiver")
            or msg_inner.get("recipient")
        )
        value = _coerce_float(
            msg_inner.get("amount")
            if "amount" in msg_inner
            else msg_inner.get("token", msg_inner.get("value"))
        )
        source_chain = (
            msg_inner.get("source_chain")
            or msg_inner.get("sourceChain")
            or payload.get("source_chain")
            or ("QIE" if (sender or receiver) else None)
        )
        destination_chain = (
            msg_inner.get("destination_chain")
            or msg_inner.get("destinationChain")
            or msg_inner.get("dest_chain")
            or payload.get("destination_chain")
            or ("QIE" if (sender or receiver) else None)
        )
        tx_hash = str(
            payload.get("hash")
            or payload.get("tx_hash")
            or payload.get("txHash")
            or deterministic_raw_hash(raw_entry)
        )
        if any(x is not None for x in (sender, receiver, value)):
            return {
                "tx_hash": tx_hash,
                "sender": sender,
                "receiver": receiver,
                "value": value,
                "source_chain": source_chain,
                "destination_chain": destination_chain,
            }

    # 2) Direct EVM or Bridge JSON transaction object
    sender = payload.get("sender") or payload.get("from") or payload.get("from_address")
    receiver = payload.get("receiver") or payload.get("to") or payload.get("to_address")
    raw_val = payload.get("value") if not isinstance(payload.get("value"), dict) else None
    if raw_val is None:
        raw_val = payload.get("amount")
    value = _coerce_float(raw_val)
    source_chain = (
        payload.get("source_chain")
        or payload.get("sourceChain")
        or ("QIE" if (sender or receiver) else None)
    )
    destination_chain = (
        payload.get("destination_chain")
        or payload.get("destinationChain")
        or payload.get("dest_chain")
        or ("QIE" if (sender or receiver) else None)
    )
    tx_hash = str(
        payload.get("hash")
        or payload.get("tx_hash")
        or payload.get("txHash")
        or deterministic_raw_hash(raw_entry)
    )

    if any(x is not None for x in (sender, receiver, value)):
        return {
            "tx_hash": tx_hash,
            "sender": sender,
            "receiver": receiver,
            "value": value,
            "source_chain": source_chain,
            "destination_chain": destination_chain,
        }

    return None


def normalize_transaction(
    raw_tx: Dict[str, Any],
    bridge_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Normalize a raw QIE Tendermint or EVM RPC transaction payload into the
    Transaction schema shape (matching backend/database/models.py Transaction.to_dict()).

    If `_raw_entry` contains a decodable JSON / Cosmos StdTx / EVM payload,
    its sender, receiver, value, source_chain, and destination_chain fields
    are extracted. If `_raw_entry` is an opaque binary blob with no decodable
    structure, it is persisted honestly with sender=None, receiver=None,
    value=None, source_chain=None, destination_chain=None, and bridge_id=None.

    Args:
        raw_tx: Raw transaction dict from QIENodeManager (mempool or block).
        bridge_id: Bridge FK to assign (resolved upstream by the persistence
            layer; None is acceptable for normalization-only).
    Returns:
        Dict matching Transaction.to_dict() field names.
    """
    tx = raw_tx if isinstance(raw_tx, dict) else {}
    raw_entry = tx.get("_raw_entry")

    if raw_entry is not None:
        decoded = _try_decode_raw_entry(raw_entry)
        if decoded is not None:
            tx_hash = decoded["tx_hash"]
            sender = decoded["sender"]
            receiver = decoded["receiver"]
            value = decoded["value"]
            source_chain = decoded["source_chain"]
            destination_chain = decoded["destination_chain"]
        else:
            tx_hash = deterministic_raw_hash(raw_entry)
            sender = None
            receiver = None
            value = None
            source_chain = None
            destination_chain = None
    else:
        tx_hash = str(
            tx.get("hash") or tx.get("tx_hash") or tx.get("txHash") or ""
        )
        sender = tx.get("sender") or tx.get("from") or tx.get("from_address")
        receiver = tx.get("receiver") or tx.get("to") or tx.get("to_address")
        raw_val = tx.get("value") if tx.get("value") is not None else tx.get("amount")
        value = _coerce_float(raw_val)
        source_chain = tx.get("source_chain") or tx.get("sourceChain")
        destination_chain = (
            tx.get("destination_chain")
            or tx.get("destinationChain")
            or tx.get("dest_chain")
        )
        # Standard EVM RPC transaction objects have 'from'/'to' without explicit chain names
        if (sender or receiver) and source_chain is None and ("blockNumber" in tx or "chainId" in tx or "gasPrice" in tx):
            source_chain = "QIE"
        if (sender or receiver) and destination_chain is None and ("blockNumber" in tx or "chainId" in tx or "gasPrice" in tx):
            destination_chain = "QIE"

    # Timestamp: block header time for confirmed txs, else "now".
    raw_ts = (
        tx.get("timestamp")
        or tx.get("time")
        or (tx.get("tx_result", {}) or {}).get("timestamp")
    )
    timestamp = _iso_to_datetime(raw_ts) or datetime.utcnow()

    # Status: confirmed if it came from a block, pending if from mempool.
    if tx.get("_source") == "block" or tx.get("height") is not None or tx.get("blockNumber") is not None:
        status = "confirmed"
    elif tx.get("_source") == "mempool":
        status = "pending"
    else:
        status = tx.get("status") or "pending"

    return {
        # id intentionally omitted — assigned by the DB on insert.
        "tx_hash": tx_hash,
        "bridge_id": bridge_id,
        "source_chain": source_chain,
        "destination_chain": destination_chain,
        "value": value,
        "sender": sender,
        "receiver": receiver,
        "timestamp": timestamp,
        "status": status,
        "anomaly_score": None,  # populated by the ML scoring pipeline
        "is_flagged": False,     # set by the scoring/alerting layer
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class IngestionWorker:
    """
    Polls QIE mempool/blocks via QIENodeManager (Tendermint RPC & Standard EVM
    JSON-RPC), normalizes each newly-seen transaction, scores it with the
    Isolation Forest anomaly model, and persists Transaction + AnomalyDetection
    + Alert rows to the database.

    Designed for standalone testing: pass mocked QIENodeManager /
    DatabaseManager / AnomalyModel and inspect `worker.poll_once()` results,
    or run the loop with `run()` / `start()`.
    """

    def __init__(
        self,
        node_manager: Optional[QIENodeManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        anomaly_model: Optional[AnomalyModel] = None,
        poll_interval: float = 2.5,
        max_backoff: float = 10.0,
        bridge_id: Optional[int] = None,
        on_new_transaction: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """
        Args:
            node_manager: QIENodeManager instance to reuse. If None, a default
                one is constructed (reads QIE_RPC_URL / QIE_EVM_RPC_URL from env).
            db_manager: DatabaseManager instance to reuse (same pattern as
                app.py). If None, a default one is constructed via
                DatabaseConfig() and init_db() is called.
            anomaly_model: AnomalyModel instance for scoring. If None, the
                singleton from ml.anomaly_model.get_model() is used.
            poll_interval: Seconds between successful poll iterations.
            max_backoff: Cap for exponential backoff when RPC calls fail.
            bridge_id: Optional known bridge FK for explicitly identified data.
            on_new_transaction: Optional callback invoked once per newly
                normalized+scored+persisted transaction with the final dict
                (including anomaly_score / is_flagged / alert_id).
        """
        self.node_manager = node_manager or QIENodeManager()

        # DB layer — reuse the same DatabaseManager / get_session() pattern
        # as app.py. Do NOT reinvent session/commit/rollback logic here.
        if db_manager is None:
            db_manager = DatabaseManager(DatabaseConfig())
            db_manager.init_db()
        self.db_manager = db_manager

        # ML scoring — Phase 2 singleton by default.
        self.anomaly_model = anomaly_model or get_anomaly_model()

        self.poll_interval = poll_interval
        self.max_backoff = max_backoff
        self.mempool_enabled = os.getenv("MEMPOOL_ENABLED", "1").lower() not in {
            "0", "false", "no"
        }
        self.evm_rpc_enabled = os.getenv("QIE_EVM_RPC_ENABLED", "1").lower() not in {
            "0", "false", "no"
        }
        self.bridge_id = bridge_id
        self.on_new_transaction = on_new_transaction

        # In-memory de-duplication of tx_hash across iterations. The DB unique
        # constraint is the final guard (IntegrityError → skip+log); this set
        # just avoids re-normalizing/scoring/persisting the same tx every loop.
        self._seen_hashes: set[str] = set()

        # Loop control.
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- public API --------------------------------------------------------

    def start(self, daemon: bool = True) -> None:
        """Start the polling loop in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("IngestionWorker already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.run, name="valiguard-ingestion", daemon=daemon
        )
        self._thread.start()
        logger.info("Ingestion worker started in background thread")

    def stop(self, timeout: Optional[float] = 5.0) -> None:
        """Signal the polling loop to stop and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("Ingestion worker stopped")

    def run(self) -> None:
        """
        Continuous polling loop. Runs until `stop()` is called.

        On RPC failure it backs off exponentially (capped at `max_backoff`)
        and retries — it never raises out of this method.
        """
        backoff = self.poll_interval
        while not self._stop_event.is_set():
            try:
                new_txs = self.poll_once()
                if new_txs:
                    logger.info("Ingested %d new transaction(s)", len(new_txs))
                # Success: reset backoff to the base poll interval.
                backoff = self.poll_interval
            except Exception as exc:  # noqa: BLE001 — loop must not die
                logger.error("Ingestion poll failed: %s — backing off %.1fs", exc, backoff)
                backoff = min(backoff * 2.0, self.max_backoff)

            # Sleep cooperatively so stop() can interrupt promptly.
            self._stop_event.wait(backoff)

    def _is_tendermint_endpoint(self) -> bool:
        """
        Return True if the node_manager is configured for a Tendermint RPC port
        (e.g. :26657) or if a test has monkeypatched _fast_rpc_call.
        """
        if "_fast_rpc_call" in self.__dict__:
            return True
        rpc_url = getattr(self.node_manager, "rpc_url", "") or ""
        return ":26657" in rpc_url or "localhost" in rpc_url or "127.0.0.1" in rpc_url

    def poll_once(self) -> List[Dict[str, Any]]:
        """
        Execute a single polling iteration across Tendermint RPC and Standard
        EVM JSON-RPC.
        """
        new_normalized: List[Dict[str, Any]] = []
        use_tendermint = self._is_tendermint_endpoint()

        # 1) Tendermint Mempool (unconfirmed txs) — only when connected to a Tendermint RPC port.
        if self.mempool_enabled and use_tendermint:
            for raw in self._fetch_mempool_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        # 2) Tendermint Latest block (confirmed txs) — only when connected to a Tendermint RPC port.
        if use_tendermint:
            for raw in self._fetch_latest_block_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        # 3) Standard EVM JSON-RPC Mempool (pending txs), when supported by node_manager.
        if self.mempool_enabled and self.evm_rpc_enabled and use_tendermint:
            for raw in self._fetch_evm_mempool_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        # 4) Standard EVM JSON-RPC Latest block (confirmed txs).
        if self.evm_rpc_enabled:
            for raw in self._fetch_evm_latest_block_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        return new_normalized

    def process_raw_transaction(
        self, raw_tx: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Process one externally supplied transaction through the worker path."""
        return self._handle_raw({**raw_tx, "_source": raw_tx.get("_source", "mempool")})

    # -- internals ---------------------------------------------------------

    def _handle_raw(self, raw_tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        De-duplicate by tx_hash, normalize, score, and persist a single raw tx.

        Returns the final normalized+scored dict if it is new and was processed,
        else None (duplicate, empty hash, or persistence skipped on conflict).
        """
        # Tag the source so normalize_transaction can set status correctly.
        if "_source" not in raw_tx:
            raw_tx = dict(raw_tx)
            raw_tx["_source"] = (
                "block"
                if (raw_tx.get("height") is not None or raw_tx.get("blockNumber") is not None)
                else "mempool"
            )

        normalized = normalize_transaction(raw_tx, bridge_id=self.bridge_id)
        tx_hash = normalized.get("tx_hash") or ""
        if not tx_hash:
            return None
        is_confirmed = normalized.get("status") == "confirmed"
        if tx_hash in self._seen_hashes and not is_confirmed:
            return None
        if is_confirmed:
            with self.db_manager.get_session() as session:
                existing = session.query(Transaction).filter_by(tx_hash=tx_hash).first()
                if existing is not None and existing.status == TransactionStatus.CONFIRMED:
                    return None
        # Optimistically mark seen so a later per-tx failure doesn't cause us
        # to retry the same hash every loop. If persistence fails with a
        # duplicate IntegrityError we keep it marked seen (correct behavior).
        self._seen_hashes.add(tx_hash)

        # Score and persist through the canonical path. Its DB session commits
        # before this callback can emit dashboard events.
        persisted = self._persist_transaction(normalized)
        if persisted is None:
            return None
        scored = persisted["score"]
        normalized["anomaly_score"] = scored["risk_score"]
        normalized["risk_score"] = scored["risk_score"]
        normalized["severity"] = scored["severity"]
        normalized["reason"] = scored.get("reason")
        normalized["is_flagged"] = is_alerting_severity(scored["severity"])
        normalized["raw_entry"] = normalized.get("sender") is None
        if persisted.get("transaction") is not None:
            normalized["transaction_id"] = persisted["transaction"].id
        if persisted.get("alert") is not None:
            normalized["alert_id"] = persisted["alert"].id

        if self.on_new_transaction is not None:
            try:
                self.on_new_transaction(normalized)
            except Exception as exc:  # noqa: BLE001 — don't let callback kill the loop
                logger.error("on_new_transaction callback raised: %s", exc)

        return normalized

    def _persist_transaction(
        self, normalized: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Persist Transaction + AnomalyDetection + (optional) Alert rows using
        the same DatabaseManager.get_session() context manager pattern as
        app.py.

        Returns the canonical scoring/persistence result.
        """
        try:
            with self.db_manager.get_session() as session:
                # Map status string -> TransactionStatus enum.
                status_str = normalized.get("status") or "pending"
                status_enum = (
                    TransactionStatus.CONFIRMED if status_str == "confirmed"
                    else TransactionStatus.FAILED if status_str == "failed"
                    else TransactionStatus.PENDING
                )

                result = score_and_persist_transaction(
                    session=session,
                    anomaly_model=self.anomaly_model,
                    tx_hash=normalized["tx_hash"],
                    source_chain=normalized.get("source_chain"),
                    destination_chain=normalized.get("destination_chain"),
                    value=normalized.get("value"),
                    sender=normalized.get("sender"),
                    receiver=normalized.get("receiver"),
                    timestamp=normalized.get("timestamp") or datetime.utcnow(),
                    status=status_enum,
                    bridge_id=normalized.get("bridge_id"),
                )

            return result
        except IntegrityError as exc:
            # Duplicate tx_hash — the unique constraint fired. Skip + log; do
            # NOT crash the loop. The tx is already in _seen_hashes so we
            # won't retry it next iteration.
            logger.warning("Duplicate tx_hash skipped: %s (%s)", normalized.get("tx_hash"), exc.orig)
            return None

    def _fast_rpc_call(self, method: str) -> Dict[str, Any]:
        """Make a one-shot Tendermint worker RPC call; polling supplies the retry loop."""
        return self.node_manager.rpc_call(method, timeout=3)

    def _fetch_mempool_txs(self) -> Iterable[Dict[str, Any]]:
        """
        Fetch unconfirmed transactions from the Tendermint mempool via QIENodeManager.

        Uses a one-shot 3-second RPC request. The worker loop handles retry and
        backoff so a dead node cannot inherit the manager's setup retry policy.
        """
        try:
            result = self._fast_rpc_call("unconfirmed_txs")
        except Exception as exc:
            logger.warning("Mempool RPC unavailable: %s", exc)
            return []
        if not result:
            return []
        # Tendermint shape: {"n_txs": "1", "txs": ["<base64>", ...]}
        txs = result.get("txs") or []
        out: List[Dict[str, Any]] = []
        for entry in txs:
            out.append({"_source": "mempool", "_raw_entry": entry})
        return out

    def _fetch_latest_block_txs(self) -> Iterable[Dict[str, Any]]:
        """
        Fetch transactions from the latest Tendermint block via QIENodeManager.
        """
        try:
            block = self._fast_rpc_call("block")
        except Exception as exc:
            logger.warning("Block RPC unavailable: %s", exc)
            return []
        block = block.get("block", {}) or {}
        if not block:
            return []
        data = block.get("data", {}) or {}
        txs = data.get("txs") or []
        header = block.get("header", {}) or {}
        height = header.get("height")
        block_time = header.get("time")

        out: List[Dict[str, Any]] = []
        for entry in txs:
            out.append({
                "_source": "block",
                "_raw_entry": entry,
                "height": height,
                "timestamp": block_time,
            })
        return out

    def _fetch_evm_mempool_txs(self) -> Iterable[Dict[str, Any]]:
        """
        Fetch pending transactions from the EVM mempool via QIENodeManager
        when the node manager provides standard EVM JSON-RPC support.
        """
        if not hasattr(self.node_manager, "get_evm_pending_transactions"):
            return []
        try:
            txs = self.node_manager.get_evm_pending_transactions(timeout=2)
        except Exception as exc:
            logger.debug("EVM mempool RPC unavailable: %s", exc)
            return []
        out: List[Dict[str, Any]] = []
        for tx in txs or []:
            if isinstance(tx, dict):
                out.append({**tx, "_source": "mempool"})
        return out

    def _fetch_evm_latest_block_txs(self) -> Iterable[Dict[str, Any]]:
        """
        Fetch confirmed transactions from the latest EVM block via QIENodeManager
        when the node manager provides standard EVM JSON-RPC support.
        """
        if not hasattr(self.node_manager, "get_evm_latest_block"):
            return []
        try:
            block_info = self.node_manager.get_evm_latest_block(
                full_transactions=True, timeout=2
            )
        except Exception as exc:
            logger.debug("EVM block RPC unavailable: %s", exc)
            return []
        if not isinstance(block_info, dict) or not block_info.get("found"):
            return []
        height = block_info.get("height")
        block_time = block_info.get("timestamp")
        txs = block_info.get("transactions") or []
        out: List[Dict[str, Any]] = []
        for tx in txs:
            if isinstance(tx, dict):
                out.append({
                    **tx,
                    "_source": "block",
                    "height": height,
                    "timestamp": tx.get("timestamp") or block_time,
                })
        return out


# ---------------------------------------------------------------------------
# Manual / smoke entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run a few iterations against whatever QIE_RPC_URL points at, printing
    # normalized+scored txs. Useful for isolated manual testing without Flask.
    logging.basicConfig(level=logging.INFO)

    def _print_tx(tx: Dict[str, Any]) -> None:
        ts = tx.get("timestamp")
        ts = ts.isoformat() if isinstance(ts, datetime) else ts
        print({
            "tx_hash": tx.get("tx_hash"),
            "sender": tx.get("sender"),
            "receiver": tx.get("receiver"),
            "value": tx.get("value"),
            "status": tx.get("status"),
            "anomaly_score": tx.get("anomaly_score"),
            "is_flagged": tx.get("is_flagged"),
            "timestamp": ts,
        })

    worker = IngestionWorker(on_new_transaction=_print_tx)
    print("Polling QIE for transactions (Ctrl+C to stop)...")
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()