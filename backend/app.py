"""
app.py
Extended Flask REST API for ValiGuard AI with QIE blockchain integration.

Features:
- QIE node status and validation endpoints (Tendermint RPC & Standard EVM RPC)
- Bridge transaction validation and anomaly detection
- Analytics and performance metrics
- Authentication and rate limiting
- Structured logging and error handling
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Dict, Any, Optional, List
from collections import defaultdict

# Ensure both repo root and backend/ are on sys.path so imports like
# `from database` and `from backend.qie_node_manager` resolve regardless of how the app is launched.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from flask import Flask, request, jsonify
from flask_cors import CORS
from pydantic import BaseModel, ValidationError, Field, field_validator
from pythonjsonlogger import jsonlogger
import requests
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# Import QIE node manager
from backend.qie_node_manager import QIENodeManager

# Import ML anomaly model (Task 5.2 — Isolation Forest Pipeline)
from ml.anomaly_model import get_model, AnomalyModel

# Import database layer (Phase 1 — Database Wiring)
from database import (
    DatabaseManager,
    DatabaseConfig,
    Bridge,
    BridgeStatus,
    Transaction,
    TransactionStatus,
    AnomalyDetection,
    SeverityLevel,
    Validator,
    Alert,
    AlertType,
)

# Import ingestion worker (Task 5.3 — Continuous Background Ingestion)
from ingestion.worker import IngestionWorker

# Web3 auth (UC-01 — nonce → signature → JWT)
from auth.jwt_auth import require_auth
from auth.routes import register_auth_routes

# Canonical 4-tier severity scale (single source of truth)
from core.severity import (
    SEVERITY_TIERS,
    is_alerting_severity,
    SEVERITY_THRESHOLDS,
    severity_from_score as _canonical_severity_from_score,
)
from core.scoring import score_and_persist_transaction
from socket_manager import SocketManager

# ===== CONFIGURATION =====
app = Flask(__name__)
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "methods": ["GET", "POST", "PATCH", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-API-Key"],
}})

# ===== WEBSOCKET REAL-TIME FEED =====
socket_manager = SocketManager(app)
socketio = socket_manager.socketio


def _emit_transaction_events(tx: Dict[str, Any]) -> None:
    """Publish a transaction after its persistence transaction commits."""
    socket_manager.emit_transaction(tx)


# Configuration
API_KEY = os.getenv("VALIGUARD_API_KEY", "dev-key-change-in-production")
RATE_LIMIT = int(os.getenv("VALIGUARD_RATE_LIMIT", "1000"))  # requests per minute
DB_PATH = os.getenv("DB_PATH", "./data/valiguard.db")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "admin@valiguard.ai")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")


# ===== LOGGING SETUP =====
def setup_logging():
    """Configure JSON structured logging."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    json_handler = logging.StreamHandler()
    json_formatter = jsonlogger.JsonFormatter()
    json_handler.setFormatter(json_formatter)
    logger.addHandler(json_handler)
    
    return logger


logger = setup_logging()

# ===== RATE LIMITING =====
request_counts = defaultdict(list)


def check_rate_limit(client_id: str) -> bool:
    """Check if client is within rate limit."""
    now = time.time()
    cutoff = now - 60  # 1 minute window
    
    request_counts[client_id] = [
        req_time for req_time in request_counts[client_id] if req_time > cutoff
    ]
    
    if len(request_counts[client_id]) >= RATE_LIMIT:
        return False
    
    request_counts[client_id].append(now)
    return True


def require_api_key(f):
    """Decorator for API key authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        
        if not api_key or api_key != API_KEY:
            logger.warning(f"Invalid API key attempt from {request.remote_addr}")
            return jsonify({"error": "Unauthorized", "code": "INVALID_API_KEY"}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function


def rate_limit(f):
    """Decorator for rate limiting."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_id = request.remote_addr
        
        if not check_rate_limit(client_id):
            logger.warning(f"Rate limit exceeded for {client_id}")
            return jsonify({"error": "Rate limit exceeded", "code": "RATE_LIMIT"}), 429
        
        return f(*args, **kwargs)
    
    return decorated_function


# ===== PYDANTIC MODELS =====
class ResponseWrapper(BaseModel):
    """Standard API response wrapper."""
    success: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    code: Optional[str] = None


class TransactionData(BaseModel):
    """Transaction data model."""
    hash: str
    from_address: str
    to_address: str
    amount: float
    timestamp: datetime
    source_chain: str
    dest_chain: str
    status: str = "pending"


class BroadcastTransactionRequest(BaseModel):
    """Transaction broadcast request."""
    tx_type: str
    from_address: str
    to_address: str
    amount: float = Field(gt=0)
    memo: Optional[str] = None
    
    @field_validator("tx_type")
    @classmethod
    def validate_tx_type(cls, v):
        if v not in ["transfer", "delegate", "redelegate", "undelegate"]:
            raise ValueError("Invalid transaction type")
        return v


class AnomalyReportRequest(BaseModel):
    """Anomaly alert request."""
    transaction_hash: str
    severity: str
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in SEVERITY_TIERS:
            raise ValueError(
                "severity must be one of: " + ", ".join(SEVERITY_TIERS)
            )
        return normalized


class ValidationRequest(BaseModel):
    """Cross-chain transaction validation request."""
    transaction_hash: str
    source_chain: str
    dest_chain: str
    amount: float = Field(gt=0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ===== UTILITY FUNCTIONS =====
def generate_request_id() -> str:
    """Generate unique request ID."""
    return f"REQ-{int(time.time() * 1000)}"


def success_response(data: Any, request_id: str) -> Dict[str, Any]:
    """Create success response."""
    return {
        "success": True,
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id,
        "data": data
    }


def error_response(message: str, code: str, request_id: str, status_code: int = 400) -> tuple:
    """Create error response."""
    response = {
        "success": False,
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id,
        "error": message,
        "code": code
    }
    return jsonify(response), status_code


def validate_request_data(data: Dict, model_class: BaseModel) -> tuple[Optional[BaseModel], Optional[tuple]]:
    """Validate request data against Pydantic model."""
    request_id = generate_request_id()
    try:
        validated = model_class(**data)
        return validated, None
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        return None, error_response(str(e), "VALIDATION_ERROR", request_id)


# ===== INITIALIZE MANAGERS =====
qie_manager = QIENodeManager()

anomaly_model = get_model(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml", "models")
)
logger.info(f"Anomaly model loaded: {anomaly_model.get_model_info()}")

# ===== DATABASE INITIALIZATION =====
db_manager = DatabaseManager(DatabaseConfig())
db_manager.init_db()
logger.info(f"Database initialized at {db_manager.config.db_url}")

# ===== WEB3 AUTH ROUTES =====
register_auth_routes(app)


def _start_node_status_broadcaster(interval: float = 10.0) -> None:
    """Broadcast node health over the WebSocket feed every `interval` seconds."""
    import threading

    def _broadcast():
        while True:
            try:
                telemetry = _fetch_node_telemetry()
                socket_manager.emit_node_status({
                    "online": telemetry.get("online", False),
                    "healthy": telemetry.get("synced", False),
                    "height": telemetry.get("block_height", 0),
                    "syncing": not telemetry.get("synced", False),
                    "rpc_url": qie_manager.rpc_url,
                    "chain_id": qie_manager.chain_id,
                })
            except Exception as exc:  # noqa: BLE001
                logger.debug("Node status broadcast failed: %s", exc)
            time.sleep(interval)

    threading.Thread(
        target=_broadcast, name="valiguard-status-feed", daemon=True
    ).start()


def get_or_create_bridge(session, address: str, chain_name: str = "QIE") -> Bridge:
    """Get an existing Bridge by address or create a default one."""
    bridge_address = address or f"bridge:{chain_name.lower()}:default"
    bridge = session.query(Bridge).filter_by(address=bridge_address).first()
    if bridge is None:
        bridge = Bridge(
            address=bridge_address,
            chain_name=chain_name,
            status=BridgeStatus.ACTIVE,
        )
        session.add(bridge)
        session.flush()
    return bridge


def severity_from_score(score_0_100: float) -> str:
    """Map a 0-100 anomaly score to a severity tier string."""
    return _canonical_severity_from_score(score_0_100)


def severity_enum(severity_str: str) -> SeverityLevel:
    """Convert a severity string to the SeverityLevel enum."""
    mapping = {
        "low": SeverityLevel.LOW,
        "medium": SeverityLevel.MEDIUM,
        "high": SeverityLevel.HIGH,
        "critical": SeverityLevel.CRITICAL,
    }
    return mapping.get(severity_str, SeverityLevel.LOW)


def _compute_bridge_analytics(session) -> Dict[str, Any]:
    """
    Aggregate real bridge counts and cross-chain route telemetry from the
    Bridge and Transaction tables.
    """
    bridges_total = int(session.query(Bridge).count() or 0)
    active_bridges = int(session.query(Bridge).filter(
        Bridge.status == BridgeStatus.ACTIVE
    ).count() or 0)

    route_map: Dict[str, Dict[str, Any]] = {}

    # 1. Include registered Bridge entities
    for b in session.query(Bridge).all():
        chain = b.chain_name or "QIE"
        entry = route_map.setdefault(chain, {
            "chain": chain,
            "status": b.status.value if b.status else "active",
            "transactions": 0,
            "volume": 0.0,
            "flagged": 0,
        })
        if b.status == BridgeStatus.ACTIVE:
            entry["status"] = "active"

    # 2. Aggregate cross-chain Transaction activity by source/destination chain
    tx_rows = session.query(
        Transaction.source_chain,
        Transaction.destination_chain,
        func.count(Transaction.id),
        func.sum(Transaction.value),
        Transaction.asset_symbol,
        Transaction.asset_address,
    ).group_by(
        Transaction.source_chain,
        Transaction.destination_chain,
        Transaction.asset_symbol,
        Transaction.asset_address,
    ).all()

    for src, dst, count, total_val, asset_symbol, asset_address in tx_rows:
        chain_label = src if (src and src != "QIE") else (dst or src or "QIE")
        entry = route_map.setdefault(chain_label, {
            "chain": chain_label,
            "status": "active",
            "transactions": 0,
            "volume": 0.0,
            "flagged": 0,
        })
        entry["transactions"] += int(count or 0)
        if asset_symbol == "QIE" and asset_address is None:
            entry["volume"] = round(entry["volume"] + float(total_val or 0.0), 2)
        entry.setdefault("asset_volumes", []).append({
            "symbol": asset_symbol, "address": asset_address,
            "volume": float(total_val or 0.0),
        })

    flagged_rows = session.query(
        Transaction.source_chain,
        Transaction.destination_chain,
        func.count(Transaction.id),
    ).filter(
        Transaction.is_flagged == True
    ).group_by(
        Transaction.source_chain,
        Transaction.destination_chain,
    ).all()

    for src, dst, f_count in flagged_rows:
        chain_label = src if (src and src != "QIE") else (dst or src or "QIE")
        if chain_label in route_map:
            route_map[chain_label]["flagged"] += int(f_count or 0)

    bridge_routes: List[Dict[str, Any]] = sorted(
        route_map.values(),
        key=lambda item: (item["transactions"], item["volume"]),
        reverse=True,
    )

    effective_active_bridges = (
        len(bridge_routes) if len(bridge_routes) > 0 else active_bridges
    )

    return {
        "bridges_total": bridges_total,
        "active_bridges": effective_active_bridges,
        "bridge_routes": bridge_routes,
    }


# ===== HEALTH CHECK =====
@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "valiguard-api"
    }), 200


# ===== ROOT / DASHBOARD ROUTE =====
@app.route("/", methods=["GET"])
@app.route("/dashboard", methods=["GET"])
@app.route("/dashboard.html", methods=["GET"])
def serve_dashboard():
    """Redirect browser requests to the Next.js dashboard or return API info."""
    frontend_url = os.getenv("FRONTEND_ORIGIN", "http://localhost:3001")
    return jsonify({
        "service": "ValiGuard AI API",
        "status": "online",
        "dashboard_url": frontend_url,
        "health_url": "/health",
    }), 200


# ===== QIE NODE ENDPOINTS =====
@app.route("/api/v1/qie/node/status", methods=["GET"])
@rate_limit
def get_qie_node_status():
    """Get QIE node status."""
    request_id = generate_request_id()
    
    try:
        telemetry = _fetch_node_telemetry()
        
        data = {
            "node": {
                "online": telemetry.get("online", False),
                "healthy": telemetry.get("synced", False),
                "height": telemetry.get("block_height", 0),
                "syncing": not telemetry.get("synced", False),
                "rpc_url": qie_manager.rpc_url,
                "evm_rpc_url": getattr(qie_manager, "evm_rpc_url", "http://localhost:8545"),
                "chain_id": qie_manager.chain_id
            },
            "response": {
                "node_info": {"moniker": telemetry.get("moniker", "")},
                "sync_info": {
                    "latest_block_height": telemetry.get("block_height", 0),
                    "catching_up": not telemetry.get("synced", False),
                },
            }
        }
        
        logger.info(f"QIE node status check: {telemetry}")
        return jsonify(success_response(data, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error getting QIE node status: {e}")
        return error_response(str(e), "QIE_NODE_ERROR", request_id)


@app.route("/api/v1/qie/evm/status", methods=["GET"])
@rate_limit
def get_qie_evm_status():
    """Get standard EVM JSON-RPC status and latest block height."""
    request_id = generate_request_id()
    try:
        block_number = qie_manager.get_evm_block_number(timeout=2)
        online = block_number is not None
        data = {
            "evm": {
                "online": online,
                "block_height": block_number or 0,
                "evm_rpc_url": qie_manager.evm_rpc_url,
                "chain_id": qie_manager.chain_id,
            }
        }
        return jsonify(success_response(data, request_id)), 200
    except Exception as e:
        logger.error(f"Error getting QIE EVM status: {e}")
        return error_response(str(e), "QIE_EVM_ERROR", request_id)


@app.route("/api/v1/qie/validator/info", methods=["GET"])
@rate_limit
@require_auth
def get_validator_info():
    """Get validator information."""
    request_id = generate_request_id()
    validator_address = request.args.get("address")
    
    if not validator_address:
        return error_response("Validator address required", "MISSING_ADDRESS", request_id)
    
    try:
        info = qie_manager.get_validator_info(validator_address)
        
        data = {
            "address": validator_address,
            "found": info.get("found", False),
            "details": info.get("data", {})
        }
        
        return jsonify(success_response(data, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error getting validator info: {e}")
        return error_response(str(e), "VALIDATOR_ERROR", request_id)


@app.route("/api/v1/qie/account/<address>", methods=["GET"])
@rate_limit
def query_account_balance(address):
    """Query account balance on QIE."""
    request_id = generate_request_id()
    
    try:
        balance = qie_manager.query_balance(address)
        
        data = {
            "address": address,
            "balance": balance.get("balance", "0"),
            "denom": balance.get("denom", "aqie"),
            "success": balance.get("success", False)
        }
        
        return jsonify(success_response(data, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error querying balance: {e}")
        return error_response(str(e), "BALANCE_QUERY_ERROR", request_id)


@app.route("/api/v1/qie/transaction/broadcast", methods=["POST"])
@rate_limit
@require_auth
def broadcast_qie_transaction():
    """Broadcast transaction to QIE network."""
    request_id = generate_request_id()
    
    try:
        validated, error = validate_request_data(request.json, BroadcastTransactionRequest)
        if error:
            return error
        
        tx_dict = {
            "type": "cosmos-sdk/StdTx",
            "value": {
                "msg": [{
                    "type": "cosmos-sdk/MsgSend",
                    "value": {
                        "from_address": validated.from_address,
                        "to_address": validated.to_address,
                        "amount": [{"denom": "aqie", "amount": str(int(validated.amount * 1_000_000))}]
                    }
                }],
                "fee": {"amount": [{"denom": "aqie", "amount": "5000"}], "gas": "200000"},
                "signatures": [],
                "memo": validated.memo or ""
            }
        }
        
        result = qie_manager.broadcast_transaction(tx_dict)
        logger.info(f"Transaction broadcast: {result.get('hash')}")
        return jsonify(success_response(result, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error broadcasting transaction: {e}")
        return error_response(str(e), "BROADCAST_ERROR", request_id)


# ===== BRIDGE VALIDATION ENDPOINTS =====
@app.route("/api/v1/bridge/validate-cross-chain", methods=["POST"])
@rate_limit
@require_auth
def validate_cross_chain():
    """Validate cross-chain transaction."""
    request_id = generate_request_id()
    
    try:
        validated, error = validate_request_data(request.json, ValidationRequest)
        if error:
            return error
        
        try:
            with db_manager.get_session() as session:
                if session.query(Transaction.id).filter_by(tx_hash=validated.transaction_hash).first():
                    return error_response("Transaction already ingested; use its stored score", "DUPLICATE_TX_HASH", request_id, 409)
                result = score_and_persist_transaction(
                    session=session,
                    anomaly_model=anomaly_model,
                    tx_hash=validated.transaction_hash,
                    source_chain=validated.source_chain,
                    destination_chain=validated.dest_chain,
                    value=float(validated.amount),
                    sender="unknown",
                    receiver="unknown",
                    timestamp=validated.timestamp,
                    status=TransactionStatus.PENDING,
                )
                score_result = result["score"]
                model_available = not score_result.get("model_unavailable") and score_result.get("risk_score") is not None
                is_valid = (not is_alerting_severity(score_result["severity"])) if model_available else None
                session.flush()
                tx_dict = result["transaction"].to_dict()
                tx_id = result["transaction"].id
                alert_id = result["alert"].id if result.get("alert") is not None else None
        except IntegrityError:
            return error_response(
                f"Transaction hash already exists: {validated.transaction_hash}",
                "DUPLICATE_TX_HASH",
                request_id,
                409,
            )

        anomaly_score_100 = score_result["risk_score"]
        confidence = score_result["confidence"]
        severity = score_result["severity"]
        _emit_transaction_events({
            **tx_dict,
            "transaction_id": tx_id,
            "alert_id": alert_id,
            "risk_score": anomaly_score_100,
            "severity": severity,
            "reason": score_result.get("reason"),
            "inference_latency_ms": score_result.get("inference_latency_ms"),
        })

        data = {
            "transaction_hash": validated.transaction_hash,
            "valid": is_valid,
            "model_available": model_available,
            "confidence": round(confidence, 2),
            "source_chain": validated.source_chain,
            "dest_chain": validated.dest_chain,
            "amount": validated.amount,
            "anomaly_score": anomaly_score_100,
            "severity": severity,
            "transaction_id": tx_id,
            "alert_id": alert_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Transaction validated and persisted: {data}")
        if not model_available:
            body = success_response(data, request_id)
            body.update(success=False, code="MODEL_UNAVAILABLE", error="Validation is unavailable until the model can score this transaction")
            return jsonify(body), 503
        return jsonify(success_response(data, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error validating transaction: {e}")
        return error_response(str(e), "VALIDATION_ERROR", request_id)


@app.route("/api/v1/bridge/anomaly-score", methods=["POST"])
@rate_limit
@require_auth
def get_anomaly_score():
    """Get ML anomaly score for transaction."""
    request_id = generate_request_id()
    
    try:
        tx_data = request.json
        
        if not tx_data or "transaction_hash" not in tx_data:
            return error_response("Transaction hash required", "MISSING_FIELD", request_id)

        with db_manager.get_session() as session:
            if session.query(Transaction.id).filter_by(tx_hash=tx_data["transaction_hash"]).first():
                return error_response("Transaction already ingested; use its stored score", "DUPLICATE_TX_HASH", request_id, 409)

        if ingestion_worker is not None:
            normalized = ingestion_worker.process_raw_transaction({
                "hash": tx_data["transaction_hash"],
                "source_chain": tx_data.get("source_chain", "QIE"),
                "destination_chain": tx_data.get(
                    "dest_chain", tx_data.get("destination_chain", "unknown")
                ),
                "amount": tx_data.get("amount", tx_data.get("value", 0.0)),
                "sender": tx_data.get("sender", tx_data.get("from_address", "unknown")),
                "receiver": tx_data.get("receiver", tx_data.get("to_address", "unknown")),
            })
            if normalized is None:
                return error_response(
                    f"Transaction hash already exists: {tx_data['transaction_hash']}",
                    "DUPLICATE_TX_HASH",
                    request_id,
                    409,
                )

            with db_manager.get_session() as session:
                persisted = session.query(Transaction).filter_by(
                    tx_hash=normalized["tx_hash"]
                ).one()
                transaction_id = persisted.id

            data = {
                "transaction_hash": normalized["tx_hash"],
                "anomaly_score": normalized["anomaly_score"],
                "severity": normalized["severity"],
                "model_confidence": None,
                "reason": normalized.get("reason"),
                "transaction_id": transaction_id,
                "alert_id": normalized.get("alert_id"),
                "timestamp": datetime.utcnow().isoformat(),
            }
            logger.info(f"Anomaly score calculated and persisted: {data}")
            return jsonify(success_response(data, request_id)), 200
        
        try:
            with db_manager.get_session() as session:
                result = score_and_persist_transaction(
                    session=session,
                    anomaly_model=anomaly_model,
                    tx_hash=tx_data["transaction_hash"],
                    source_chain=tx_data.get("source_chain", "QIE"),
                    destination_chain=tx_data.get(
                        "dest_chain", tx_data.get("destination_chain", "unknown")
                    ),
                    value=float(tx_data.get("amount", tx_data.get("value", 0.0)) or 0.0),
                    sender=tx_data.get("sender", tx_data.get("from_address", "unknown")),
                    receiver=tx_data.get("receiver", tx_data.get("to_address", "unknown")),
                    timestamp=datetime.utcnow(),
                    status=TransactionStatus.PENDING,
                )
                tx_dict = result["transaction"].to_dict()
                tx_id = result["transaction"].id
                alert_id = result["alert"].id if result.get("alert") is not None else None
        except IntegrityError:
            return error_response(
                f"Transaction hash already exists: {tx_data['transaction_hash']}",
                "DUPLICATE_TX_HASH",
                request_id,
                409,
            )

        score_result = result["score"]
        raw_risk = score_result.get("risk_score")
        anomaly_score_100 = float(raw_risk) if raw_risk is not None else None
        severity = score_result["severity"]
        confidence = score_result["confidence"]
        reason = score_result["reason"]
        _emit_transaction_events({
            **tx_dict,
            "transaction_id": tx_id,
            "alert_id": alert_id,
            "risk_score": anomaly_score_100,
            "severity": severity,
            "reason": reason,
            "inference_latency_ms": score_result.get("inference_latency_ms"),
        })
        
        data = {
            "transaction_hash": tx_data.get("transaction_hash"),
            "anomaly_score": round(anomaly_score_100, 2) if anomaly_score_100 is not None else None,
            "severity": severity,
            "model_confidence": confidence,
            "reason": reason,
            "transaction_id": tx_id,
            "alert_id": alert_id,
            "inference_latency_ms": score_result.get("inference_latency_ms"),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Anomaly score calculated and persisted: {data}")
        return jsonify(success_response(data, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error calculating anomaly score: {e}")
        return error_response(str(e), "ANOMALY_ERROR", request_id)


@app.route("/api/v1/bridge/history", methods=["GET"])
@rate_limit
@require_auth
def get_transaction_history():
    """Get paginated transaction validation history ordered chronologically."""
    request_id = generate_request_id()
    
    limit = int(request.args.get("limit", 15))
    offset = int(request.args.get("offset", 0))
    
    with db_manager.get_session() as session:
        query = session.query(Transaction).order_by(
            Transaction.timestamp.desc(),
            Transaction.id.desc(),
        )
        total = int(query.count() or 0)
        transactions = query.offset(offset).limit(limit).all()
        history = [tx.to_dict() for tx in transactions]
    
    data = {
        "total": total,
        "limit": limit,
        "offset": offset,
        "transactions": history
    }
    
    return jsonify(success_response(data, request_id)), 200


@app.route("/api/v1/bridge/alert", methods=["POST"])
@rate_limit
@require_auth
def send_anomaly_alert():
    """Send anomaly alert."""
    request_id = generate_request_id()
    
    try:
        validated, error = validate_request_data(request.json, AnomalyReportRequest)
        if error:
            return error
        
        alert_data = {
            "transaction_hash": validated.transaction_hash,
            "severity": validated.severity,
            "reason": validated.reason,
            "timestamp": datetime.utcnow().isoformat(),
            "request_id": request_id
        }
        
        alert_id = None
        try:
            with db_manager.get_session() as session:
                tx = session.query(Transaction).filter_by(tx_hash=validated.transaction_hash).first()
                if tx is None:
                    bridge = get_or_create_bridge(session, address=None, chain_name="QIE")
                    tx = Transaction(
                        tx_hash=validated.transaction_hash,
                        bridge_id=bridge.id,
                        source_chain="QIE",
                        destination_chain="unknown",
                        value=0.0,
                        sender="unknown",
                        receiver="unknown",
                        timestamp=validated.timestamp,
                        status=TransactionStatus.PENDING,
                    )
                    session.add(tx)
                    session.flush()

                alert = Alert(
                    transaction_id=tx.id,
                    alert_type=AlertType.ANOMALY,
                    severity=severity_enum(validated.severity),
                    message=validated.reason,
                )
                session.add(alert)
                session.flush()
                alert_id = alert.id
        except IntegrityError:
            return error_response(
                f"Transaction hash already exists: {validated.transaction_hash}",
                "DUPLICATE_TX_HASH",
                request_id,
                409,
            )
        
        logger.warning(f"Alert sent and persisted (alert_id={alert_id}): {alert_data}")
        
        if WEBHOOK_URL:
            try:
                requests.post(WEBHOOK_URL, json=alert_data, timeout=5)
            except Exception as e:
                logger.error(f"Webhook error: {e}")
        
        return jsonify(success_response({"alert_id": alert_id or request_id, "sent": True}, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error sending alert: {e}")
        return error_response(str(e), "ALERT_ERROR", request_id)


def _parse_alert_datetime(value: Optional[str], field_name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc


@app.route("/api/v1/alerts", methods=["GET"])
@rate_limit
@require_auth
def get_alerts():
    """Query persisted alerts with explicit audit filters and pagination."""
    request_id = generate_request_id()
    severity = request.args.get("severity")
    if severity and severity.lower() not in SEVERITY_TIERS:
        return error_response("Invalid severity filter", "INVALID_SEVERITY", request_id, 400)

    resolved = request.args.get("resolved")
    resolved_value = None
    if resolved is not None:
        if resolved.lower() not in ("true", "false"):
            return error_response("resolved must be true or false", "INVALID_RESOLVED", request_id, 400)
        resolved_value = resolved.lower() == "true"

    try:
        from_date = _parse_alert_datetime(request.args.get("from"), "from")
        to_date = _parse_alert_datetime(request.args.get("to"), "to")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
    except ValueError as exc:
        return error_response(str(exc), "INVALID_FILTER", request_id, 400)

    if limit < 1 or limit > 100 or offset < 0:
        return error_response("limit must be 1-100 and offset must be non-negative", "INVALID_PAGINATION", request_id, 400)
    if from_date and to_date and from_date > to_date:
        return error_response("from must be earlier than to", "INVALID_DATE_RANGE", request_id, 400)

    with db_manager.get_session() as session:
        query = session.query(Alert).join(Transaction)
        if severity:
            query = query.filter(Alert.severity == SeverityLevel(severity.lower()))
        if from_date:
            query = query.filter(Alert.created_at >= from_date)
        if to_date:
            if len(request.args.get("to", "")) == 10:
                to_date = to_date + timedelta(days=1) - timedelta(microseconds=1)
            query = query.filter(Alert.created_at <= to_date)
        if resolved_value is not None:
            query = query.filter(Alert.is_resolved == resolved_value)
        if request.args.get("tx_hash"):
            query = query.filter(Transaction.tx_hash.ilike(f"%{request.args['tx_hash']}%"))

        total = int(query.count() or 0)
        rows = query.order_by(Alert.created_at.desc(), Alert.id.desc()).offset(offset).limit(limit).all()
        items = []
        for alert in rows:
            anomaly = max(
                alert.transaction.anomalies,
                key=lambda item: item.detected_at or datetime.min,
                default=None,
            )
            item = alert.to_dict()
            item.update({
                "alert_id": alert.id,
                "tx_hash": alert.transaction.tx_hash,
                "reason": anomaly.reason if anomaly else None,
                "anomaly_score": anomaly.anomaly_score if anomaly else alert.transaction.anomaly_score,
                "model_confidence": anomaly.confidence if anomaly else None,
            })
            items.append(item)

    return jsonify(success_response({
        "total": total,
        "limit": limit,
        "offset": offset,
        "alerts": items,
        "items": items,
    }, request_id)), 200


@app.route("/api/v1/alerts/<int:alert_id>/resolve", methods=["PATCH"])
@rate_limit
@require_auth
def resolve_alert(alert_id: int):
    """Resolve an alert and notify connected dashboards after commit."""
    request_id = generate_request_id()
    resolved_at = datetime.utcnow()
    with db_manager.get_session() as session:
        alert = session.query(Alert).filter_by(id=alert_id).first()
        if alert is None:
            return error_response("Alert not found", "ALERT_NOT_FOUND", request_id, 404)
        if not alert.is_resolved:
            alert.is_resolved = True
            alert.resolved_at = resolved_at
        resolved_at = alert.resolved_at
        tx_hash = alert.transaction.tx_hash

    payload = {
        "alert_id": alert_id,
        "tx_hash": tx_hash,
        "is_resolved": True,
        "resolved_at": resolved_at.isoformat() if resolved_at else None,
    }
    socket_manager.emit_alert_resolved(payload)
    return jsonify(success_response(payload, request_id)), 200


@app.route("/api/v1/alerts/resolve-bulk", methods=["POST", "PATCH"])
@rate_limit
@require_auth
def resolve_alerts_bulk():
    """Resolve multiple alerts in a single atomic transaction."""
    request_id = generate_request_id()
    body = request.get_json(silent=True) or {}
    raw_ids = body.get("alert_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return error_response("alert_ids list is required", "INVALID_REQUEST", request_id, 400)

    try:
        alert_ids = [int(aid) for aid in raw_ids]
    except (ValueError, TypeError):
        return error_response("alert_ids must be integers", "INVALID_REQUEST", request_id, 400)

    resolved_at = datetime.utcnow()
    resolved_payloads = []
    with db_manager.get_session() as session:
        alerts = session.query(Alert).filter(Alert.id.in_(alert_ids), Alert.is_resolved.is_(False)).all()
        for alert in alerts:
            alert.is_resolved = True
            alert.resolved_at = resolved_at
            resolved_payloads.append({
                "alert_id": alert.id,
                "tx_hash": alert.transaction.tx_hash if alert.transaction else None,
                "is_resolved": True,
                "resolved_at": resolved_at.isoformat(),
            })

    for item in resolved_payloads:
        socket_manager.emit_alert_resolved(item)

    return jsonify(success_response({
        "resolved_count": len(resolved_payloads),
        "resolved_ids": [p["alert_id"] for p in resolved_payloads],
    }, request_id)), 200


# ===== ANALYTICS ENDPOINTS =====
def _open_anomalies_24h(session, now):
    """Distinct currently actionable transactions first alerted in the last 24h."""
    return session.query(Alert.transaction_id).join(Transaction).filter(
        Alert.alert_type == AlertType.ANOMALY,
        Alert.is_resolved.is_(False),
        Alert.severity.in_([SeverityLevel.MEDIUM, SeverityLevel.HIGH, SeverityLevel.CRITICAL]),
        Transaction.is_flagged.is_(True),
        Alert.created_at >= now - timedelta(hours=24),
        Alert.created_at <= now,
    ).distinct().count()


@app.route("/api/v1/analytics/open-anomalies", methods=["GET"])
@rate_limit
@require_auth
def get_open_anomalies():
    now = datetime.utcnow()
    with db_manager.get_session() as session:
        count = _open_anomalies_24h(session, now)
    return jsonify(success_response({
        "open_anomalies_24h": count,
        "window_start": (now - timedelta(hours=24)).isoformat() + "Z",
        "window_end": now.isoformat() + "Z",
    }, generate_request_id())), 200


@app.route("/api/v1/analytics/daily-stats", methods=["GET"])
@rate_limit
@require_auth
def get_daily_stats():
    """Get daily statistics from the database."""
    request_id = generate_request_id()

    date_str = request.args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify(error_response("Invalid date format. Use YYYY-MM-DD.", "INVALID_DATE", request_id, 400)), 400

    next_date = target_date + timedelta(days=1)

    with db_manager.get_session() as session:
        total_transactions = int(session.query(Transaction).filter(
            Transaction.timestamp >= target_date,
            Transaction.timestamp < next_date
        ).count() or 0)

        anomalies_detected = int(session.query(AnomalyDetection).filter(
            AnomalyDetection.detected_at >= target_date,
            AnomalyDetection.detected_at < next_date,
            AnomalyDetection.severity.in_([SeverityLevel.MEDIUM, SeverityLevel.HIGH, SeverityLevel.CRITICAL]),
        ).count() or 0)

        open_anomalies_24h = _open_anomalies_24h(session, datetime.utcnow())
        scored_query = session.query(Transaction).filter(
            Transaction.timestamp >= target_date,
            Transaction.timestamp < next_date,
            Transaction.anomaly_score.isnot(None),
        )
        scored_count = scored_query.count()
        low_risk_count = scored_query.filter(Transaction.anomaly_score < SEVERITY_THRESHOLDS["medium"]).count()
        low_risk_rate = round(low_risk_count / scored_count * 100, 2) if scored_count else None

        avg_score_result = session.query(AnomalyDetection).filter(
            AnomalyDetection.detected_at >= target_date,
            AnomalyDetection.detected_at < next_date
        ).with_entities(
            func.avg(AnomalyDetection.anomaly_score)
        ).scalar()
        avg_anomaly_score = round(float(avg_score_result or 0), 2)

        daily_volume_result = session.query(Transaction).filter(
            Transaction.timestamp >= target_date,
            Transaction.timestamp < next_date,
            Transaction.asset_symbol == "QIE",
            Transaction.asset_address.is_(None),
        ).with_entities(
            func.sum(Transaction.value)
        ).scalar()
        total_volume = round(float(daily_volume_result or 0.0), 2)
        second = (func.strftime("%Y-%m-%d %H:%M:%S", Transaction.timestamp)
                  if session.bind.dialect.name == "sqlite"
                  else func.date_trunc("second", Transaction.timestamp))
        throughput = session.query(func.count(Transaction.id).label("count")).filter(
            Transaction.timestamp >= target_date, Transaction.timestamp < next_date,
        ).group_by(second).subquery()
        peak_tps = session.query(func.max(throughput.c.count)).scalar()


        critical_alerts = int(session.query(Alert).filter(
            Alert.created_at >= target_date,
            Alert.created_at < next_date,
            Alert.severity == SeverityLevel.CRITICAL
        ).count() or 0)

        high_alerts = int(session.query(Alert).filter(
            Alert.created_at >= target_date,
            Alert.created_at < next_date,
            Alert.severity == SeverityLevel.HIGH
        ).count() or 0)

        counts = dict(
            session.query(
                AnomalyDetection.severity, func.count(AnomalyDetection.id)
            ).filter(
                AnomalyDetection.detected_at >= target_date,
                AnomalyDetection.detected_at < next_date
            ).group_by(AnomalyDetection.severity).all()
        )
        severity_counts = {
            "low": int(counts.get(SeverityLevel.LOW, 0) or 0),
            "medium": int(counts.get(SeverityLevel.MEDIUM, 0) or 0),
            "high": int(counts.get(SeverityLevel.HIGH, 0) or 0),
            "critical": int(counts.get(SeverityLevel.CRITICAL, 0) or 0),
        }

        bridge_analytics = _compute_bridge_analytics(session)

    data = {
        "date": date_str,
        "total_transactions": total_transactions,
        "total_volume": total_volume,
        "volume_unit": "QIE",
        "peak_tps": int(peak_tps) if peak_tps is not None else None,
        "anomalies_detected": anomalies_detected,
        "open_anomalies_24h": open_anomalies_24h,
        "scored_transactions": scored_count,
        "low_risk_rate": low_risk_rate,
        "validation_success_rate": low_risk_rate,  # Backward-compatible alias: risk screening, not chain execution.
        "avg_anomaly_score": avg_anomaly_score,
        "critical_alerts": critical_alerts,
        "high_alerts": high_alerts,
        "severity_counts": severity_counts,
        "active_bridges": bridge_analytics["active_bridges"],
        "bridges_total": bridge_analytics["bridges_total"],
        "bridge_routes": bridge_analytics["bridge_routes"],
    }

    return jsonify(success_response(data, request_id)), 200


def _load_model_metrics(metrics_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the real evaluation metrics written by ml/train_model.py."""
    if metrics_path is None:
        metrics_path = os.path.join(
            os.path.dirname(__file__), "ml", "models", "metrics_latest.json"
        )
    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not read model metrics: {exc}")
        return {
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1_score": None,
            "model_version": anomaly_model.model_version,
            "error": "Model metrics unavailable — run backend/ml/train_model.py",
        }


@app.route("/api/v1/analytics/model-accuracy", methods=["GET"])
@rate_limit
@require_auth
def get_model_accuracy():
    """Get ML model performance metrics (from the actual trained artifact)."""
    request_id = generate_request_id()
    return jsonify(success_response(_load_model_metrics(), request_id)), 200


NODE_TELEMETRY_TTL_SECONDS = 30
_node_telemetry_cache: Dict[str, Any] = {"data": None, "fetched_at": 0.0}


def _probe_node_telemetry() -> Dict[str, Any]:
    """
    Single fast Tendermint /status probe with Standard EVM eth_blockNumber
    fallback for Public RPC nodes (plain requests, no retry adapter, 3s timeout).
    Never raises.
    """
    base = {
        "available": False,
        "online": False,
        "synced": False,
        "block_height": 0,
        "chain_id": qie_manager.chain_id,
        "rpc_url": qie_manager.rpc_url,
    }

    def _post_rpc(url: str, payload: Dict[str, Any]):
        return requests.post(url, json=payload, timeout=3)

    try:
        # 1. Try Tendermint /status first
        try:
            response = _post_rpc(
                qie_manager.rpc_url,
                {"jsonrpc": "2.0", "id": 1, "method": "status", "params": {}},
            )
            response.raise_for_status()
            payload = response.json() or {}
            result = payload.get("result", {}) or {}
            sync_info = result.get("sync_info", {}) or {}
            if sync_info:
                return {
                    **base,
                    "available": True,
                    "online": True,
                    "synced": not bool(sync_info.get("catching_up", True)),
                    "block_height": int(sync_info.get("latest_block_height", 0) or 0),
                    "moniker": (result.get("node_info", {}) or {}).get("moniker", ""),
                }
        except requests.Timeout:
            return base
        except Exception as td_exc:
            logger.debug(f"Tendermint status probe fell back to EVM: {td_exc}")

        # 2. Fallback for Public EVM JSON-RPC endpoints
        evm_url = getattr(qie_manager, "evm_rpc_url", None) or qie_manager.rpc_url
        evm_response = _post_rpc(
            evm_url,
            {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
        )
        evm_response.raise_for_status()
        hex_height = (evm_response.json() or {}).get("result")
        if isinstance(hex_height, str) and hex_height.startswith(("0x", "0X")):
            height = int(hex_height, 16)
            return {
                **base,
                "available": True,
                "online": True,
                "synced": height > 0,
                "block_height": height,
                "moniker": qie_manager.moniker,
            }
        return base
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Node telemetry probe failed: {exc}")
        return base


def _fetch_node_telemetry() -> Dict[str, Any]:
    """Live node telemetry for the analytics endpoints, cached for 30s."""
    now = time.time()
    if (
        _node_telemetry_cache["data"] is not None
        and now - _node_telemetry_cache["fetched_at"] < NODE_TELEMETRY_TTL_SECONDS
    ):
        return _node_telemetry_cache["data"]
    data = _probe_node_telemetry()
    _node_telemetry_cache["data"] = data
    _node_telemetry_cache["fetched_at"] = now
    return data


def _fetch_chain_voting_power() -> Dict[str, float]:
    """Return chain-reported voting power as percentages keyed by address."""
    try:
        result = qie_manager.get_validator_set()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Validator-set RPC failed: %s", exc)
        return {}

    if not result.get("success"):
        return {}

    raw_values = {}
    for validator in result.get("validators", []):
        address = (
            validator.get("address")
            or validator.get("operator_address")
            or validator.get("account_address")
        )
        power = validator.get("voting_power", validator.get("power"))
        if address is None or power is None:
            continue
        try:
            raw_values[str(address).lower()] = float(power)
        except (TypeError, ValueError):
            continue

    total_power = sum(raw_values.values())
    if total_power <= 0:
        return {}

    return {
        address: round(power / total_power * 100, 2)
        for address, power in raw_values.items()
    }


@app.route("/api/v1/analytics/validator-stats", methods=["GET"])
@rate_limit
@require_auth
def get_validator_stats():
    """
    Validator stats from real sources only:
      - DB aggregates from the validators table (all online and offline validators)
      - Per-validator transaction/alert counts joined on Transaction.sender
      - Live node telemetry (sync status, block height) with graceful fallback
    """
    request_id = generate_request_id()
    chain_voting_power = _fetch_chain_voting_power()

    with db_manager.get_session() as session:
        total_validators = int(session.query(Validator).count() or 0)
        active_validators = int(session.query(Validator).filter(
            Validator.is_active == True
        ).count() or 0)
        avg_uptime_result = session.query(
            func.avg(Validator.uptime_percentage)
        ).scalar()
        total_staked_result = session.query(
            func.sum(Validator.stake_amount)
        ).scalar()
        transactions_total = int(session.query(Transaction).count() or 0)
        alerts_total = int(session.query(Alert).count() or 0)
        alerts_unresolved = int(session.query(Alert).filter(
            Alert.is_resolved == False
        ).count() or 0)

        top_validators_rows = session.query(Validator).order_by(
            Validator.is_active.desc(),
            Validator.stake_amount.desc(),
        ).all()
        active_stake = sum(
            float(v.stake_amount or 0) for v in top_validators_rows if v.is_active
        )
        top_validators = []
        for v in top_validators_rows:
            stake = float(v.stake_amount or 0)
            db_voting_power = (
                round((stake / active_stake) * 100, 2)
                if (v.is_active and active_stake > 0)
                else 0.0
            )
            voting_power = (
                chain_voting_power.get(v.address.lower(), db_voting_power)
                if v.is_active
                else 0.0
            )
            voting_power_source = (
                "rpc" if v.address.lower() in chain_voting_power else "db"
            )
            tx_count = int(session.query(Transaction).filter(
                Transaction.sender == v.address
            ).count() or 0)
            alert_count = int(session.query(Alert).join(
                Transaction, Alert.transaction_id == Transaction.id
            ).filter(
                Transaction.sender == v.address
            ).count() or 0)
            top_validators.append({
                "address": v.address,
                "name": v.name,
                "stake_amount": v.stake_amount,
                "voting_power": voting_power,
                "source": voting_power_source,
                "uptime": round(float(v.uptime_percentage), 2) if v.uptime_percentage is not None else None,
                "is_active": v.is_active,
                "transactions": tx_count,
                "alerts": alert_count,
            })

        bridge_analytics = _compute_bridge_analytics(session)

    data = {
        "total_validators": total_validators,
        "active_validators": active_validators,
        "avg_uptime": round(float(avg_uptime_result), 2) if avg_uptime_result is not None else None,
        "total_staked": f"{round(float(total_staked_result or 0))} aqie",
        "transactions_total": transactions_total,
        "alerts_total": alerts_total,
        "alerts_unresolved": alerts_unresolved,
        "top_validators": top_validators,
        "active_bridges": bridge_analytics["active_bridges"],
        "bridges_total": bridge_analytics["bridges_total"],
        "bridge_routes": bridge_analytics["bridge_routes"],
        "node": _fetch_node_telemetry(),
    }
    return jsonify(success_response(data, request_id)), 200


# ===== BACKGROUND SERVICES =====
ingestion_worker = None
_background_services_started = False


def start_background_services() -> None:
    """Start import-time background services after module initialization."""
    global ingestion_worker, _background_services_started

    if _background_services_started:
        return
    _background_services_started = True

    if os.getenv("VALIGUARD_INGESTION_WORKER", "1") != "1":
        return

    _is_reloader_parent = (
        os.getenv("FLASK_ENV") == "development"
        and os.getenv("WERKZEUG_RUN_MAIN") != "true"
    )
    if _is_reloader_parent:
        logger.info("Ingestion worker deferred to Werkzeug reloader child process")
        return

    ingestion_worker = IngestionWorker(
        node_manager=qie_manager,
        db_manager=db_manager,
        anomaly_model=anomaly_model,
        on_new_transaction=_emit_transaction_events,
    )
    ingestion_worker.start()
    logger.info("Ingestion worker started in background thread")
    _start_node_status_broadcaster()


# ===== ERROR HANDLERS =====
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    request_id = generate_request_id()
    return error_response("Endpoint not found", "NOT_FOUND", request_id, 404)


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    request_id = generate_request_id()
    logger.error(f"Internal server error: {error}")
    return error_response("Internal server error", "INTERNAL_ERROR", request_id, 500)


# ===== MAIN =====
start_background_services()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"

    logger.info(f"Starting ValiGuard AI API on port {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=debug,
                 allow_unsafe_werkzeug=True)
