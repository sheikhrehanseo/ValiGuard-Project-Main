from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional

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
from database.models import (
    Alert,
    AlertType,
    AnomalyDetection,
    Bridge,
    BridgeStatus,
    SeverityLevel,
    Transaction,
    TransactionStatus,
)

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
# Normalization
# ---------------------------------------------------------------------------

def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Best-effort conversion of arbitrary RPC payload values to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso_to_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; return None on failure."""
    if not value:
        return None
    try:
        # Tendermint timestamps look like "2026-07-19T12:34:56.123456789Z"
        # Truncate nanoseconds to microseconds for fromisoformat compatibility.
        ts = value.rstrip("Z")
        if "." in ts:
            head, frac = ts.split(".", 1)
            ts = f"{head}.{frac[:6]}"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def normalize_transaction(
    raw_tx: Dict[str, Any],
    bridge_id: Optional[int] = None,
    default_source_chain: str = "QIE",
    default_destination_chain: str = "QIE",
) -> Dict[str, Any]:
    """
    Normalize a raw QIE/Tendermint transaction payload into the Transaction
    schema shape (matching backend/database/models.py Transaction.to_dict()).

    Tendermint block txs are byte-encoded; in practice the QIE RPC layer (and
    the mocked test fixtures) expose a JSON-ish structure. This function is
    defensive: it pulls well-known fields when present and falls back to sane
    defaults so the caller always gets a complete, schema-shaped dict.

    Args:
        raw_tx: Raw transaction dict from QIENodeManager (mempool or block).
        bridge_id: Bridge FK to assign (resolved upstream by the persistence
            layer in a later sub-step; None is acceptable for normalization-only).
        default_source_chain: Fallback source chain when not derivable from tx.
        default_destination_chain: Fallback destination chain.

    Returns:
        Dict matching Transaction.to_dict() field names:
            tx_hash, bridge_id, source_chain, destination_chain, value,
            sender, receiver, timestamp, status, anomaly_score, is_flagged,
            created_at, updated_at  (id omitted — assigned by the DB).
    """
    # Tendermint txs in a block come wrapped under "tx_result" or as a raw
    # hex string; the QIE app layer may also surface decoded fields. We handle
    # the common shapes defensively.
    tx = raw_tx if isinstance(raw_tx, dict) else {}

    # tx_hash: prefer explicit hash fields, else fall back to a provided id.
    tx_hash = (
        tx.get("hash")
        or tx.get("tx_hash")
        or tx.get("txHash")
        or (tx.get("tx_result", {}) or {}).get("hash")
        or ""
    )
    # Some Tendermint responses encode the hash as bytes/hex; normalize to str.
    if isinstance(tx_hash, (bytes, bytearray)):
        tx_hash = tx_hash.hex()
    tx_hash = str(tx_hash) if tx_hash else ""

    # Sender / receiver / value: try a few common key spellings used by the
    # QIE/Cosmos SDK message layer and the mocked fixtures.
    sender = (
        tx.get("sender")
        or tx.get("from")
        or tx.get("from_address")
        or (tx.get("tx_result", {}) or {}).get("sender")
        or ""
    )
    receiver = (
        tx.get("receiver")
        or tx.get("to")
        or tx.get("to_address")
        or (tx.get("tx_result", {}) or {}).get("receiver")
        or ""
    )
    value = _coerce_float(
        tx.get("value")
        or tx.get("amount")
        or (tx.get("tx_result", {}) or {}).get("value")
        or 0.0
    )

    # Chains: derive if the payload carries them, else use defaults.
    source_chain = tx.get("source_chain") or tx.get("sourceChain") or default_source_chain
    destination_chain = (
        tx.get("destination_chain")
        or tx.get("destinationChain")
        or default_destination_chain
    )

    # Timestamp: block header time for confirmed txs, else "now".
    raw_ts = (
        tx.get("timestamp")
        or tx.get("time")
        or (tx.get("tx_result", {}) or {}).get("timestamp")
    )
    timestamp = _iso_to_datetime(raw_ts) or datetime.utcnow()

    # Status: confirmed if it came from a block, pending if from mempool.
    if tx.get("_source") == "block" or tx.get("height") is not None:
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
        "anomaly_score": 0.0,   # populated by the ML scoring pipeline (Task 5.2)
        "is_flagged": False,     # set by the scoring/alerting layer
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class IngestionWorker:
    """
    Polls QIE mempool/blocks via QIENodeManager, normalizes each newly-seen
    transaction, scores it with the Phase 2 anomaly model, and persists
    Transaction + AnomalyDetection + Alert rows to the database.

    Designed for standalone testing: pass mocked QIENodeManager /
    DatabaseManager / AnomalyModel and inspect `worker.poll_once()` results,
    or run the loop with `run()` / `start()`.
    """

    def __init__(
        self,
        node_manager: Optional[QIENodeManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        anomaly_model: Optional[AnomalyModel] = None,
        poll_interval: float = 5.0,
        max_backoff: float = 60.0,
        bridge_id: Optional[int] = None,
        default_bridge_chain: str = "QIE",
        on_new_transaction: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """
        Args:
            node_manager: QIENodeManager instance to reuse. If None, a default
                one is constructed (reads QIE_RPC_URL etc. from env).
            db_manager: DatabaseManager instance to reuse (same pattern as
                app.py). If None, a default one is constructed via
                DatabaseConfig() and init_db() is called.
            anomaly_model: AnomalyModel instance for scoring. If None, the
                singleton from ml.anomaly_model.get_model() is used.
            poll_interval: Seconds between successful poll iterations.
            max_backoff: Cap for exponential backoff when RPC calls fail.
            bridge_id: Bridge FK to stamp onto normalized transactions. If
                None, a default bridge is get_or_create'd per source chain
                (same helper pattern as app.py).
            default_bridge_chain: Chain name used when creating a default bridge.
            on_new_transaction: Optional callback invoked once per newly
                normalized+scored+persisted transaction with the final dict
                (including anomaly_score / is_flagged). Used by callers/tests
                to collect output.
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
        self.bridge_id = bridge_id
        self.default_bridge_chain = default_bridge_chain
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

    def poll_once(self) -> List[Dict[str, Any]]:
        """
        Execute a single polling iteration: fetch mempool + latest block txs,
        normalize the unseen ones, score each with the anomaly model, persist
        Transaction + AnomalyDetection + Alert rows, fire the callback for
        each, and return the final normalized+scored dicts.

        Returns:
            List of normalized Transaction-shaped dicts (with anomaly_score
            and is_flagged populated) that were newly seen and processed in
            this iteration.

        Raises:
            Exception: if the underlying QIENodeManager RPC calls raise
            unexpectedly (the `run()` loop catches and backs off). DB and ML
            errors are caught per-transaction so they never crash the loop.
        """
        new_normalized: List[Dict[str, Any]] = []

        # 1) Mempool (unconfirmed txs).
        for raw in self._fetch_mempool_txs():
            normalized = self._handle_raw(raw)
            if normalized is not None:
                new_normalized.append(normalized)

        # 2) Latest block (confirmed txs).
        for raw in self._fetch_latest_block_txs():
            normalized = self._handle_raw(raw)
            if normalized is not None:
                new_normalized.append(normalized)

        return new_normalized

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
            raw_tx["_source"] = "block" if raw_tx.get("height") is not None else "mempool"

        normalized = normalize_transaction(raw_tx, bridge_id=self.bridge_id)
        tx_hash = normalized.get("tx_hash") or ""
        if not tx_hash or tx_hash in self._seen_hashes:
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
        app.py. Resolves bridge_id via get_or_create_bridge when not provided.

        Returns the canonical scoring/persistence result.
        Any other DB error is logged and re-raised so get_session() rolls back
        — but _handle_raw() callers (the loop) catch broadly so the loop lives.
        """
        try:
            with self.db_manager.get_session() as session:
                # Resolve bridge FK if not pinned. Same helper pattern as app.py.
                bridge_id = normalized.get("bridge_id")
                if bridge_id is None:
                    bridge = self._get_or_create_bridge(
                        session,
                        address=None,
                        chain_name=normalized.get("source_chain") or self.default_bridge_chain,
                    )
                    bridge_id = bridge.id

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
                    source_chain=normalized.get("source_chain", "QIE"),
                    destination_chain=normalized.get("destination_chain", "QIE"),
                    value=normalized.get("value", 0.0),
                    sender=normalized.get("sender", ""),
                    receiver=normalized.get("receiver", ""),
                    timestamp=normalized.get("timestamp") or datetime.utcnow(),
                    status=status_enum,
                    bridge_id=bridge_id,
                )

            return result
        except IntegrityError as exc:
            # Duplicate tx_hash — the unique constraint fired. Skip + log; do
            # NOT crash the loop. The tx is already in _seen_hashes so we
            # won't retry it next iteration.
            logger.warning("Duplicate tx_hash skipped: %s (%s)", normalized.get("tx_hash"), exc.orig)
            return None

    def _get_or_create_bridge(self, session, address: Optional[str], chain_name: str) -> Bridge:
        """
        Get an existing Bridge by address or create a default one.

        Mirrors app.py's get_or_create_bridge helper exactly so the worker
        shares the same default-bridge convention. We don't import the helper
        from app.py to avoid starting Flask as a side effect.
        """
        bridge_address = address or f"bridge:{chain_name.lower()}:default"
        bridge = session.query(Bridge).filter_by(address=bridge_address).first()
        if bridge is None:
            bridge = Bridge(
                address=bridge_address,
                chain_name=chain_name,
                status=BridgeStatus.ACTIVE,
            )
            session.add(bridge)
            session.flush()  # populate bridge.id without full commit
        return bridge

    def _fetch_mempool_txs(self) -> Iterable[Dict[str, Any]]:
        """
        Fetch unconfirmed transactions from the mempool via QIENodeManager.

        Reuses the manager's `_rpc_call` (the same private helper its public
        methods use) so we do NOT duplicate any HTTP/session/retry logic. If the
        manager ever grows a public `get_mempool()` method, swap this in.
        """
        result = self.node_manager._rpc_call("unconfirmed_txs")
        if not result:
            return []
        # Tendermint shape: {"n_txs": "1", "txs": ["<base64>", ...]}
        txs = result.get("txs") or []
        out: List[Dict[str, Any]] = []
        for idx, entry in enumerate(txs):
            # Entries are usually base64-encoded byte strings; surface them as
            # dicts with a synthetic hash so normalization has something to
            # de-duplicate on. Real decoding happens in the persistence sub-step.
            if isinstance(entry, dict):
                entry = dict(entry)
                entry.setdefault("_source", "mempool")
                out.append(entry)
            else:
                out.append({
                    "_source": "mempool",
                    "hash": str(entry) or f"mempool-{idx}",
                    "raw": entry,
                })
        return out

    def _fetch_latest_block_txs(self) -> Iterable[Dict[str, Any]]:
        """
        Fetch transactions from the latest block via QIENodeManager's public
        `get_latest_block()` method (reused — no duplicated RPC logic).
        """
        block_result = self.node_manager.get_latest_block()
        if not block_result.get("found"):
            return []
        block_data = block_result.get("data", {}) or {}
        block = block_data.get("block", {}) or {}
        data = block.get("data", {}) or {}
        txs = data.get("txs") or []
        header = block.get("header", {}) or {}
        height = header.get("height")
        block_time = header.get("time")

        out: List[Dict[str, Any]] = []
        for idx, entry in enumerate(txs):
            if isinstance(entry, dict):
                entry = dict(entry)
            else:
                entry = {"raw": entry}
            entry.setdefault("_source", "block")
            entry.setdefault("height", height)
            entry.setdefault("timestamp", block_time)
            entry.setdefault("hash", entry.get("hash") or f"block-{height}-{idx}")
            out.append(entry)
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
