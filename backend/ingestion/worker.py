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

# Canonical 4-tier severity scale
from core.severity import (
    is_alerting_severity,
    severity_from_score as _canonical_severity_from_score,
)
from core.scoring import score_and_persist_transaction

# Phase 1 DB layer
from database.db import DatabaseManager, DatabaseConfig
from database.models import (
    Bridge,
    BridgeStatus,
    SeverityLevel,
    Transaction,
    TransactionStatus,
    Validator,
)

logger = logging.getLogger(__name__)


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
        ts = str(value).rstrip("Z")
        if "+" in ts:
            ts = ts.split("+", 1)[0]
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
    structured fields.
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


def _classify_evm_input_route(input_hex: str, value: Optional[float]) -> str:
    """Classify an EVM transaction by its 4-byte function selector and value."""
    selector = (input_hex or "0x")[:10].lower()
    if selector in ("0xa9059cbb", "0x23b872dd", "0x095ea7b3"):
        return "QIE Token Bridge"
    if selector in ("0x38ed1739", "0x7ff36ab5", "0x18cbafe5", "0xe8e33700"):
        return "QIEDEX Liquidity Pool"
    if selector and selector != "0x" and len(selector) >= 10:
        return "QIE Smart Contract"
    if (value or 0.0) > 0:
        return "QIE Native Bridge"
    return "QIE Smart Contract"


def normalize_transaction(
    raw_tx: Dict[str, Any],
    bridge_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Normalize a raw QIE Tendermint or EVM RPC transaction payload into the
    Transaction schema shape (with honest zero values for 0-QIE contract calls).
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
        if (sender or receiver) and source_chain is None and ("blockNumber" in tx or "chainId" in tx or "gasPrice" in tx):
            input_hex = str(tx.get("input") or "0x")
            source_chain = _classify_evm_input_route(input_hex, value)
        if (sender or receiver) and destination_chain is None and ("blockNumber" in tx or "chainId" in tx or "gasPrice" in tx):
            destination_chain = "QIE"

    raw_ts = (
        tx.get("timestamp")
        or tx.get("time")
        or (tx.get("tx_result", {}) or {}).get("timestamp")
    )
    timestamp = _iso_to_datetime(raw_ts) or datetime.utcnow()

    if tx.get("status") in ("pending", "confirmed", "failed"):
        status = tx["status"]
    elif tx.get("_source") == "block" or tx.get("height") is not None or tx.get("blockNumber") is not None:
        status = "confirmed"
    elif tx.get("_source") == "mempool":
        status = "pending"
    else:
        status = "pending"

    bridge_chain_name = tx.get("bridge_chain_name") or source_chain
    bridge_address = tx.get("bridge_address")
    if not bridge_address and bridge_chain_name:
        if receiver and str(bridge_chain_name) != "QIE Native Transfer":
            bridge_address = str(receiver).lower()
        else:
            bridge_address = "bridge:qie:native-transfer"

    return {
        "tx_hash": tx_hash,
        "bridge_id": bridge_id,
        "source_chain": source_chain,
        "destination_chain": destination_chain,
        "value": value,
        "asset_symbol": tx.get("asset_symbol", "QIE" if value is not None and sender else None),
        "asset_address": tx.get("asset_address"),
        "sender": sender,
        "receiver": receiver,
        "bridge_address": bridge_address,
        "bridge_chain_name": bridge_chain_name,
        "timestamp": timestamp,
        "status": status,
        "anomaly_score": None,
        "is_flagged": False,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


class IngestionWorker:
    """
    Polls QIE mempool/blocks via QIENodeManager (Tendermint RPC, Standard EVM
    JSON-RPC, and QIE Mainnet Explorer API v2), normalizes each newly-seen
    transaction, scores it with the Isolation Forest anomaly model, and
    persists Transaction + AnomalyDetection + Alert rows to the database.
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
        self.node_manager = node_manager or QIENodeManager()

        if db_manager is None:
            db_manager = DatabaseManager(DatabaseConfig())
            db_manager.init_db()
        self.db_manager = db_manager

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

        self._last_evm_block_height: Optional[int] = None
        self._last_tm_block_height: Optional[int] = None
        self._last_explorer_sync: float = 0.0
        self._last_validator_sync: float = 0.0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

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
        """Continuous polling loop. Runs until `stop()` is called."""
        backoff = self.poll_interval
        while not self._stop_event.is_set():
            try:
                new_txs = self.poll_once()
                if new_txs:
                    logger.info("Ingested %d new transaction(s)", len(new_txs))
                backoff = self.poll_interval
            except Exception as exc:  # noqa: BLE001
                logger.error("Ingestion poll failed: %s — backing off %.1fs", exc, backoff)
                backoff = min(backoff * 2.0, self.max_backoff)

            self._stop_event.wait(backoff)

    def _is_tendermint_endpoint(self) -> bool:
        """Recognize local nodes and HTTPS Tendermint gateways alike."""
        if "_fast_rpc_call" in self.__dict__:
            return True
        if hasattr(self.node_manager, "uses_tendermint_rpc"):
            return self.node_manager.uses_tendermint_rpc()
        rpc_url = getattr(self.node_manager, "rpc_url", "") or ""
        return ":26657" in rpc_url or "localhost" in rpc_url or "127.0.0.1" in rpc_url

    def _is_public_qie_gateway(self) -> bool:
        """Return True when connected to a public QIE gateway (*.qie.digital)."""
        if hasattr(self.node_manager, "is_public_qie_gateway"):
            return bool(self.node_manager.is_public_qie_gateway())
        return False

    def poll_once(self) -> List[Dict[str, Any]]:
        """
        Execute a single polling iteration across Tendermint RPC, Standard
        EVM JSON-RPC, and QIE Mainnet Explorer REST API v2.
        """
        new_normalized: List[Dict[str, Any]] = []
        use_tendermint = self._is_tendermint_endpoint()
        use_public_qie = self._is_public_qie_gateway()

        now = time.time()
        if use_public_qie:
            if now - self._last_validator_sync >= 30.0:
                self._sync_live_qie_validators()
                self._last_validator_sync = now

            if now - self._last_explorer_sync >= 10.0:
                for raw in self._fetch_explorer_recent_txs():
                    normalized = self._handle_raw(raw)
                    if normalized is not None:
                        new_normalized.append(normalized)
                self._last_explorer_sync = now

        # 1) Tendermint Mempool (unconfirmed txs).
        if self.mempool_enabled and use_tendermint:
            for raw in self._fetch_mempool_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        # 2) Tendermint Latest block (confirmed txs).
        if use_tendermint:
            for raw in self._fetch_latest_block_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        # 3) Standard EVM JSON-RPC Mempool (pending txs).
        if self.mempool_enabled and self.evm_rpc_enabled:
            for raw in self._fetch_evm_mempool_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        # 4) Standard EVM JSON-RPC Latest blocks (confirmed txs).
        if self.evm_rpc_enabled:
            for raw in self._fetch_evm_latest_block_txs():
                normalized = self._handle_raw(raw)
                if normalized is not None:
                    new_normalized.append(normalized)

        return new_normalized

    def _sync_live_qie_validators(self) -> None:
        """
        Upsert real QIE Mainnet validators (online & offline) and clean up
        any legacy placeholder validator rows.
        """
        if not hasattr(self.node_manager, "get_live_network_validators"):
            return
        try:
            live_validators = self.node_manager.get_live_network_validators()
            if not live_validators:
                return
            with self.db_manager.get_session() as session:
                session.query(Validator).filter(
                    (Validator.address.like("qie1validator%"))
                    | (Validator.address.like("qie1valoper%"))
                    | (Validator.name.like("QIE Validator #%"))
                ).delete(synchronize_session=False)

                for v_data in live_validators:
                    addr = v_data["address"]
                    existing = session.query(Validator).filter_by(address=addr).first()
                    if existing is None:
                        session.add(Validator(
                            address=addr,
                            name=v_data["name"],
                            stake_amount=float(v_data["stake_amount"]),
                            uptime_percentage=v_data.get("uptime_percentage"),
                            is_active=bool(v_data["is_active"]),
                        ))
                    else:
                        existing.name = v_data["name"]
                        existing.stake_amount = float(v_data["stake_amount"])
                        existing.uptime_percentage = v_data.get("uptime_percentage")
                        existing.is_active = bool(v_data["is_active"])
        except Exception as exc:
            logger.debug(f"Live validator sync skipped: {exc}")

    def _fetch_explorer_recent_txs(self) -> Iterable[Dict[str, Any]]:
        """Fetch recent confirmed & pending transactions from QIE Explorer API v2."""
        if not hasattr(self.node_manager, "get_explorer_recent_transactions"):
            return []
        try:
            txs = self.node_manager.get_explorer_recent_transactions(limit=30)
            return list(reversed(txs))
        except Exception as exc:
            logger.debug(f"Explorer recent txs fetch failed: {exc}")
            return []

    def process_raw_transaction(
        self, raw_tx: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Process one externally supplied transaction through the worker path."""
        return self._handle_raw({**raw_tx, "_source": raw_tx.get("_source", "mempool")})

    def _handle_raw(self, raw_tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """De-duplicate by tx_hash, normalize, score, and persist a single raw tx."""
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
        with self.db_manager.get_session() as session:
            existing = session.query(Transaction).filter_by(tx_hash=tx_hash).first()
            if existing is not None:
                if existing.status == TransactionStatus.FAILED and normalized["status"] == "confirmed":
                    return None  # Inclusion-only feeds cannot undo an observed execution failure.
                enriches_asset = (
                    (normalized.get("asset_address") and not existing.asset_address)
                    or (normalized.get("asset_symbol") and not existing.asset_symbol)
                )
                if existing.status.value == normalized["status"] and not enriches_asset:
                    return None
                if existing.asset_address and not normalized.get("asset_address"):
                    for key in ("value", "asset_symbol", "asset_address", "sender", "receiver", "source_chain", "destination_chain"):
                        normalized[key] = getattr(existing, key)
                if normalized["status"] == "pending":
                    return None  # Never regress a settled transaction to pending.
        normalized["is_update"] = existing is not None

        persisted = self._persist_transaction(normalized)
        if persisted is None:
            return None
        scored = persisted["score"]
        normalized["anomaly_score"] = scored["risk_score"]
        normalized["risk_score"] = scored["risk_score"]
        normalized["severity"] = scored["severity"]
        normalized["reason"] = scored.get("reason")
        normalized["inference_latency_ms"] = scored.get("inference_latency_ms")
        normalized["is_flagged"] = is_alerting_severity(scored["severity"])
        normalized["raw_entry"] = normalized.get("sender") is None
        if persisted.get("transaction") is not None:
            normalized["transaction_id"] = persisted["transaction"].id
        if persisted.get("alert") is not None:
            normalized["alert_id"] = persisted["alert"].id

        if self.on_new_transaction is not None:
            try:
                self.on_new_transaction(normalized)
            except Exception as exc:  # noqa: BLE001
                logger.error("on_new_transaction callback raised: %s", exc)

        return normalized

    def _persist_transaction(
        self, normalized: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Persist Transaction + AnomalyDetection + (optional) Alert rows."""
        try:
            with self.db_manager.get_session() as session:
                status_str = normalized.get("status") or "pending"
                status_enum = (
                    TransactionStatus.CONFIRMED if status_str == "confirmed"
                    else TransactionStatus.FAILED if status_str == "failed"
                    else TransactionStatus.PENDING
                )

                # Group strictly by canonical bridge route (max 6 routes)
                bridge_id = normalized.get("bridge_id")
                bridge_addr = normalized.get("bridge_address")
                bridge_chain = normalized.get("bridge_chain_name")
                if (
                    bridge_id is None
                    and bridge_addr
                    and bridge_chain
                    and self._is_public_qie_gateway()
                ):
                    bridge = session.query(Bridge).filter_by(address=bridge_addr).first()
                    if bridge is None:
                        bridge = Bridge(
                            address=bridge_addr,
                            chain_name=str(bridge_chain)[:50],
                            status=BridgeStatus.ACTIVE,
                        )
                        session.add(bridge)
                        session.flush()
                    bridge_id = bridge.id

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
                    bridge_id=bridge_id,
                    asset_symbol=normalized.get("asset_symbol"),
                    asset_address=normalized.get("asset_address"),
                )

            return result
        except IntegrityError as exc:
            logger.warning("Transaction write failed: %s", normalized.get("tx_hash"))
            raise

    def _fast_rpc_call(self, method: str) -> Dict[str, Any]:
        """Make a one-shot Tendermint worker RPC call."""
        return self.node_manager.rpc_call(method, timeout=3)

    def _fetch_mempool_txs(self) -> Iterable[Dict[str, Any]]:
        """Fetch unconfirmed transactions from the Tendermint mempool via QIENodeManager."""
        try:
            result = self._fast_rpc_call("unconfirmed_txs")
        except Exception as exc:
            logger.warning("Mempool RPC unavailable: %s", exc)
            return []
        if not result:
            return []
        txs = result.get("txs") or []
        out: List[Dict[str, Any]] = []
        for entry in txs:
            out.append({"_source": "mempool", "_raw_entry": entry})
        return out

    def _fetch_latest_block_txs(self) -> Iterable[Dict[str, Any]]:
        """Fetch transactions from the latest Tendermint block via QIENodeManager."""
        try:
            block = self._fast_rpc_call("block")
        except Exception as exc:
            logger.warning("Block RPC unavailable: %s", exc)
            return []
        block = block.get("block", {}) or {}
        if not block:
            return []
        current_height = int((block.get("header") or {}).get("height") or 0)
        if current_height <= 0:
            return
        start_height = self._last_tm_block_height + 1 if self._last_tm_block_height is not None else current_height
        for height in range(start_height, min(current_height, start_height + 99) + 1):
            candidate = block
            if height != current_height:
                candidate = (self.node_manager.rpc_call("block", params={"height": str(height)}, timeout=3) or {}).get("block")
            if not candidate or int(candidate.get("header", {}).get("height") or 0) != height:
                return
            header = candidate.get("header") or {}
            for entry in (candidate.get("data") or {}).get("txs") or []:
                yield {"_source": "block", "_raw_entry": entry,
                       "height": height, "timestamp": header.get("time")}
            self._last_tm_block_height = height

    def _fetch_evm_mempool_txs(self) -> Iterable[Dict[str, Any]]:
        """Fetch pending transactions from the EVM mempool via QIENodeManager."""
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
                out.append({**tx, "_source": "mempool", "status": "pending"})
        return out

    def _fetch_evm_latest_block_txs(self) -> Iterable[Dict[str, Any]]:
        """
        Fetch confirmed transactions from recent EVM blocks via QIENodeManager,
        scanning any blocks missed since the previous poll iteration.
        """
        if not hasattr(self.node_manager, "get_evm_latest_block"):
            return []
        try:
            latest_info = self.node_manager.get_evm_latest_block(
                full_transactions=True, timeout=2
            )
        except Exception as exc:
            logger.debug("EVM block RPC unavailable: %s", exc)
            return []
        if not isinstance(latest_info, dict) or not latest_info.get("found"):
            return []

        current_height = int(latest_info.get("height") or 0)
        start_height = (self._last_evm_block_height + 1
                        if self._last_evm_block_height is not None else current_height)
        # Bound each poll's work without dropping the rest of the backlog.
        for height in range(start_height, min(current_height, start_height + 99) + 1):
            try:
                block = latest_info if height == current_height else self.node_manager.get_evm_block_by_number(
                    height, full_transactions=True, timeout=3
                )
            except Exception:
                return
            if not isinstance(block, dict) or not block.get("found") or int(block.get("height") or 0) != height:
                return  # Retry the missing block on the next poll.
            for tx in block.get("transactions") or []:
                if isinstance(tx, dict):
                    status = "confirmed"
                    if hasattr(self.node_manager, "get_evm_transaction_receipt"):
                        receipt = self.node_manager.get_evm_transaction_receipt(tx["hash"], timeout=3)
                        if not isinstance(receipt, dict) or receipt.get("status") is None:
                            return  # Retry this block until its execution results are available.
                        if receipt["status"] in (0, "0x0", "0x00"):
                            status = "failed"
                    yield {**tx, "_source": "block", "status": status,
                           "height": height, "timestamp": tx.get("timestamp") or block.get("timestamp")}
            # The caller has persisted every yielded transaction before advancing.
            self._last_evm_block_height = height
