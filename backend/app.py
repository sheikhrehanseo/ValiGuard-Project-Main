"""
app.py
Extended Flask REST API for ValiGuard AI with QIE blockchain integration.

Features:
- QIE node status and validation endpoints
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
from typing import Dict, Any, Optional
from collections import defaultdict

# Ensure the backend/ directory is on sys.path so the `database` package
# (which uses absolute imports like `from database.models import ...`) resolves
# regardless of whether the app is launched as `python -m backend.app` from the
# project root or directly from within backend/.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, join_room
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
    SEVERITY_THRESHOLDS as CANONICAL_SEVERITY_THRESHOLDS,
    severity_from_score as _canonical_severity_from_score,
)

# ===== CONFIGURATION =====
app = Flask(__name__)
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-API-Key"],
}})

# ===== WEBSOCKET REAL-TIME FEED (Phase 2 — Live Alert Stream) =====
# Threading async_mode matches the ingestion worker's background-thread
# design (no eventlet/gevent monkey-patching required).
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


@socketio.on("connect")
def _handle_socket_connect():
    """Every dashboard client joins the shared 'dashboard' room."""
    join_room("dashboard")


def _emit_transaction_events(tx: Dict[str, Any]) -> None:
    """
    Push a newly ingested transaction to all dashboard clients over the
    WebSocket feed. Called from the ingestion worker via on_new_transaction.
    """
    from core.severity import severity_from_score

    timestamp = tx.get("timestamp")
    payload = {
        "tx_hash": tx.get("tx_hash"),
        "value": tx.get("value"),
        "sender": tx.get("sender"),
        "receiver": tx.get("receiver"),
        "status": tx.get("status"),
        "anomaly_score": tx.get("anomaly_score"),
        "is_flagged": tx.get("is_flagged"),
        "severity": severity_from_score(tx.get("anomaly_score", 0)),
        "source_chain": tx.get("source_chain"),
        "destination_chain": tx.get("destination_chain"),
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
    }
    socketio.emit("new_transaction", payload, to="dashboard")
    # Alert-level events for the live alert feed (matches DB alert rule: High+)
    if payload["is_flagged"] or payload["severity"] in ("high", "critical"):
        socketio.emit("new_alert", {
            "tx_hash": payload["tx_hash"],
            "severity": payload["severity"],
            "anomaly_score": payload["anomaly_score"],
            "message": f"Anomaly score {payload['anomaly_score']:.1f} on {payload['tx_hash']}",
            "timestamp": payload["timestamp"],
        }, to="dashboard")

# Configuration
API_KEY = os.getenv("VALIGUARD_API_KEY", "dev-key-change-in-production")
RATE_LIMIT = 100  # requests per minute
DB_PATH = os.getenv("DB_PATH", "./data/valiguard.db")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "admin@valiguard.ai")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# ===== LOGGING SETUP =====
def setup_logging():
    """Configure JSON structured logging."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # JSON handler
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
    
    # Remove old requests
    request_counts[client_id] = [req_time for req_time in request_counts[client_id] if req_time > cutoff]
    
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
    severity: str = Field(pattern="^(low|medium|high|critical)$")
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

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

# Initialize anomaly model singleton (Task 5.2)
anomaly_model = get_model()
logger.info(f"Anomaly model loaded: {anomaly_model.get_model_info()}")

# ===== DATABASE INITIALIZATION (Phase 1 — Database Wiring) =====# Initialize a DatabaseManager at app startup. SQLite by default (file-based for
# persistence across restarts), PostgreSQL via DATABASE_URL env var.
db_manager = DatabaseManager(DatabaseConfig())
db_manager.init_db()
logger.info(f"Database initialized at {db_manager.config.db_url}")

# ===== INGESTION WORKER (Task 5.3 — Background Ingestion on Boot) =====
# Start the continuous QIE mempool/block ingestion worker in a daemon
# background thread when the Flask app boots. Reuse the already-initialized
# qie_manager / db_manager / anomaly_model singletons so we don't double-init
# the DB, ML model, or QIENodeManager.
#
# Set VALIGUARD_INGESTION_WORKER=0 to disable (e.g. for unit tests).
#
# Under the Flask debug reloader the module is imported twice (once in the
# parent process, once in the child that actually serves requests). We defer
# startup to the child (WERKZEUG_RUN_MAIN == "true"); in production (gunicorn /
# uWSGI) there is no reloader so the worker starts once per process.
ingestion_worker = None
if os.getenv("VALIGUARD_INGESTION_WORKER", "1") == "1":
    _is_reloader_parent = (
        os.getenv("FLASK_ENV") == "development"
        and os.getenv("WERKZEUG_RUN_MAIN") != "true"
    )
    if not _is_reloader_parent:
        ingestion_worker = IngestionWorker(
            node_manager=qie_manager,
            db_manager=db_manager,
            anomaly_model=anomaly_model,
            on_new_transaction=_emit_transaction_events,
        )
        ingestion_worker.start()
        logger.info("Ingestion worker started in background thread")
        _start_node_status_broadcaster()
    else:
        logger.info("Ingestion worker deferred to Werkzeug reloader child process")

# ===== WEB3 AUTH ROUTES (UC-01 — nonce → signature → JWT) =====
register_auth_routes(app)

def _start_node_status_broadcaster(interval: float = 10.0) -> None:
    """Broadcast node health over the WebSocket feed every `interval` seconds."""
    import threading
    import time as _time

    def _broadcast():
        while True:
            try:
                status = qie_manager.get_node_status()
                health = qie_manager.check_node_health()
                socketio.emit("node_status", {
                    "online": status.get("online", False),
                    "healthy": health.get("healthy", False),
                    "height": health.get("height", 0),
                    "syncing": not health.get("healthy", False),
                    "rpc_url": qie_manager.rpc_url,
                    "chain_id": qie_manager.chain_id,
                }, to="dashboard")
            except Exception as exc:  # noqa: BLE001 — broadcaster must not die
                logger.debug("Node status broadcast failed: %s", exc)
            time.sleep(interval)

    threading.Thread(target=_broadcast, name="valiguard-status-feed",
                     daemon=True).start()


def get_or_create_bridge(session, address: str, chain_name: str = "QIE") -> Bridge:
    """
    Get an existing Bridge by address or create a default one.

    Transactions require a bridge_id FK, so we ensure a Bridge row exists
    before attaching any Transaction to it. A default bridge is created
    when the source chain is not explicitly registered.

    Args:
        session: SQLAlchemy session
        address: Bridge contract address (defaults to a sentinel if empty)
        chain_name: Source chain name

    Returns:
        Bridge instance attached to the session
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


def severity_from_score(score_0_100: float) -> str:
    """Map a 0-100 anomaly score to a severity tier string.

    Delegates to the canonical scale in backend/core/severity.py.
    """
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

# ===== HEALTH CHECK =====
@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "valiguard-api"
    }), 200

# ===== DASHBOARD ROUTE =====
@app.route("/", methods=["GET"])
@app.route("/dashboard", methods=["GET"])
@app.route("/dashboard.html", methods=["GET"])
def serve_dashboard():
    """Serve the dashboard HTML."""
    try:
        dashboard_path = os.path.join(os.path.dirname(__file__), "../frontend_legacy/dashboard.html")
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html"}
    except FileNotFoundError:
        return jsonify({"error": "Dashboard not found"}), 404

# ===== FRONTEND FILES =====
@app.route("/api-client.js", methods=["GET"])
def serve_api_client():
    """Serve API client JavaScript."""
    try:
        file_path = os.path.join(os.path.dirname(__file__), "../frontend_legacy/api-client.js")
        with open(file_path, "r") as f:
            return f.read(), 200, {"Content-Type": "application/javascript"}
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

@app.route("/dashboard.js", methods=["GET"])
def serve_dashboard_js():
    """Serve dashboard JavaScript."""
    try:
        file_path = os.path.join(os.path.dirname(__file__), "../frontend_legacy/dashboard.js")
        with open(file_path, "r") as f:
            return f.read(), 200, {"Content-Type": "application/javascript"}
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

# ===== QIE NODE ENDPOINTS =====
@app.route("/api/v1/qie/node/status", methods=["GET"])
@rate_limit
def get_qie_node_status():
    """Get QIE node status."""
    request_id = generate_request_id()
    
    try:
        health = qie_manager.check_node_health()
        status = qie_manager.get_node_status()
        
        data = {
            "node": {
                "online": status.get("online", False),
                "healthy": health.get("healthy", False),
                "height": health.get("height", 0),
                "syncing": not health.get("healthy", False),
                "rpc_url": qie_manager.rpc_url,
                "chain_id": qie_manager.chain_id
            },
            "response": status.get("data", {})
        }
        
        logger.info(f"QIE node status check: {health}")
        return jsonify(success_response(data, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error getting QIE node status: {e}")
        return error_response(str(e), "QIE_NODE_ERROR", request_id)

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
def broadcast_qie_transaction():
    """Broadcast transaction to QIE network."""
    request_id = generate_request_id()
    
    try:
        # Validate request
        validated, error = validate_request_data(request.json, BroadcastTransactionRequest)
        if error:
            return error
        
        # Build transaction
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
        
        # Broadcast
        result = qie_manager.broadcast_transaction(tx_dict)
        
        logger.info(f"Transaction broadcast: {result.get('hash')}")
        
        return jsonify(success_response(result, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error broadcasting transaction: {e}")
        return error_response(str(e), "BROADCAST_ERROR", request_id)

# ===== BRIDGE VALIDATION ENDPOINTS =====
@app.route("/api/v1/bridge/validate-cross-chain", methods=["POST"])
@rate_limit
def validate_cross_chain():
    """Validate cross-chain transaction."""
    request_id = generate_request_id()
    
    try:
        validated, error = validate_request_data(request.json, ValidationRequest)
        if error:
            return error
        
        # Create a minimal transaction object for ML scoring (Task 5.2)
        class _TxForScoring:
            """Minimal transaction wrapper for anomaly_model.score()."""
            def __init__(self, value: float, sender: str, timestamp: datetime):
                self.value = value
                self.sender = sender
                self.timestamp = timestamp

        temp_tx = _TxForScoring(
            value=float(validated.amount),
            sender="unknown",
            timestamp=validated.timestamp
        )

        # Get real anomaly score from Isolation Forest model (Task 5.2)
        score_result = anomaly_model.score(temp_tx)
        anomaly_score_100 = score_result["risk_score"]
        confidence = score_result["confidence"]
        severity = score_result["severity"].lower()
        is_valid = anomaly_score_100 < 60

        # Persist to the database (Phase 1 — Database Wiring)
        try:
            with db_manager.get_session() as session:
                bridge = get_or_create_bridge(session, address=None, chain_name=validated.source_chain)
                tx = Transaction(
                    tx_hash=validated.transaction_hash,
                    bridge_id=bridge.id,
                    source_chain=validated.source_chain,
                    destination_chain=validated.dest_chain,
                    value=float(validated.amount),
                    sender="unknown",
                    receiver="unknown",
                    timestamp=validated.timestamp,
                    status=TransactionStatus.CONFIRMED if is_valid else TransactionStatus.FAILED,
                    anomaly_score=anomaly_score_100,
                    is_flagged=(severity in ("high", "critical")),
                )
                session.add(tx)
                session.flush()
                tx_id = tx.id
        except IntegrityError:
            return error_response(
                f"Transaction hash already exists: {validated.transaction_hash}",
                "DUPLICATE_TX_HASH",
                request_id,
                409,
            )

        data = {
            "transaction_hash": validated.transaction_hash,
            "valid": is_valid,
            "confidence": round(confidence, 2),
            "source_chain": validated.source_chain,
            "dest_chain": validated.dest_chain,
            "amount": validated.amount,
            "anomaly_score": anomaly_score_100,
            "severity": severity,
            "transaction_id": tx_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Transaction validated and persisted: {data}")
        
        return jsonify(success_response(data, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error validating transaction: {e}")
        return error_response(str(e), "VALIDATION_ERROR", request_id)

@app.route("/api/v1/bridge/anomaly-score", methods=["POST"])
@rate_limit
def get_anomaly_score():
    """Get ML anomaly score for transaction."""
    request_id = generate_request_id()
    
    try:
        tx_data = request.json
        
        if not tx_data or "transaction_hash" not in tx_data:
            return error_response("Transaction hash required", "MISSING_FIELD", request_id)
        
        # Create a minimal transaction object for ML scoring (Task 5.2)
        class _TxForScoring:
            """Minimal transaction wrapper for anomaly_model.score()."""
            def __init__(self, value: float, sender: str, timestamp: datetime):
                self.value = value
                self.sender = sender
                self.timestamp = timestamp

        temp_tx = _TxForScoring(
            value=float(tx_data.get("amount", tx_data.get("value", 0.0)) or 0.0),
            sender=tx_data.get("sender", tx_data.get("from_address", "unknown")),
            timestamp=datetime.utcnow()
        )

        # Get real anomaly score from Isolation Forest model (Task 5.2)
        score_result = anomaly_model.score(temp_tx)
        # Standardize on 0-100 internally; convert only at the response boundary.
        anomaly_score_100 = float(score_result["risk_score"])
        severity = score_result["severity"].lower()
        confidence = score_result["confidence"]
        reason = score_result["reason"]
        model_version = score_result["model_version"]
        extracted_features = score_result.get("features", [])

        # Persist AnomalyDetection + Alert rows (Phase 1 — Database Wiring)
        tx_id = None
        try:
            with db_manager.get_session() as session:
                # Look up the transaction by hash; create a lightweight row if it
                # doesn't exist yet so the AnomalyDetection FK is satisfied.
                tx = session.query(Transaction).filter_by(tx_hash=tx_data["transaction_hash"]).first()
                if tx is None:
                    source_chain = tx_data.get("source_chain", "QIE")
                    bridge = get_or_create_bridge(session, address=None, chain_name=source_chain)
                    tx = Transaction(
                        tx_hash=tx_data["transaction_hash"],
                        bridge_id=bridge.id,
                        source_chain=source_chain,
                        destination_chain=tx_data.get("dest_chain", tx_data.get("destination_chain", "unknown")),
                        value=float(tx_data.get("amount", tx_data.get("value", 0.0)) or 0.0),
                        sender=tx_data.get("sender", tx_data.get("from_address", "unknown")),
                        receiver=tx_data.get("receiver", tx_data.get("to_address", "unknown")),
                        timestamp=datetime.utcnow(),
                        status=TransactionStatus.PENDING,
                        anomaly_score=round(anomaly_score_100, 2),
                        is_flagged=(severity in ("high", "critical")),
                    )
                    session.add(tx)
                    session.flush()
                else:
                    tx.anomaly_score = round(anomaly_score_100, 2)
                    tx.is_flagged = severity in ("high", "critical")
                    session.flush()

                tx_id = tx.id

                # Persist the actual extracted feature vector for audit/debug.
                feature_names = (
                    anomaly_model.feature_extractor.get_feature_names()
                    if anomaly_model.feature_extractor else
                    ["value_normalized", "frequency_deviation", "hour_sin", "hour_cos", "day_sin", "day_cos"]
                )
                features_used = {
                    name: float(val)
                    for name, val in zip(feature_names, extracted_features)
                } if extracted_features else {}

                anomaly = AnomalyDetection(
                    transaction_id=tx.id,
                    anomaly_score=anomaly_score_100,
                    confidence=confidence,
                    features_used=features_used,
                    model_version=model_version,
                    severity=severity_enum(severity),
                    reason=reason,
                )
                session.add(anomaly)

                # Generate an Alert row when severity reaches High or Critical.
                # Threshold aligns with severity_from_score (>= 60 = high).
                if severity in ("high", "critical"):
                    alert = Alert(
                        transaction_id=tx.id,
                        alert_type=AlertType.ANOMALY,
                        severity=severity_enum(severity),
                        message=f"Anomaly score {round(anomaly_score_100, 2)} ({severity}): {reason}",
                    )
                    session.add(alert)
        except IntegrityError:
            return error_response(
                f"Transaction hash already exists: {tx_data['transaction_hash']}",
                "DUPLICATE_TX_HASH",
                request_id,
                409,
            )
        
        data = {
            "transaction_hash": tx_data.get("transaction_hash"),
            "anomaly_score": round(anomaly_score_100, 2),
            "severity": severity,
            "model_confidence": confidence,
            "reason": reason,
            "transaction_id": tx_id,
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
    """Get transaction validation history."""
    request_id = generate_request_id()
    
    limit = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))
    
    # Query the Transaction table (Phase 1 — Database Wiring)
    with db_manager.get_session() as session:
        query = session.query(Transaction).order_by(Transaction.created_at.desc())
        total = query.count()
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
        
        # Persist an Alert row linked to the transaction (Phase 1 — Database Wiring)
        alert_id = None
        try:
            with db_manager.get_session() as session:
                tx = session.query(Transaction).filter_by(tx_hash=validated.transaction_hash).first()
                if tx is None:
                    # Create a lightweight transaction row so the Alert FK is satisfied
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
        
        # TODO: Send email/webhook
        if WEBHOOK_URL:
            try:
                requests.post(WEBHOOK_URL, json=alert_data, timeout=5)
            except Exception as e:
                logger.error(f"Webhook error: {e}")
        
        return jsonify(success_response({"alert_id": alert_id or request_id, "sent": True}, request_id)), 200
    
    except Exception as e:
        logger.error(f"Error sending alert: {e}")
        return error_response(str(e), "ALERT_ERROR", request_id)

# ===== ANALYTICS ENDPOINTS =====
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
        total_transactions = session.query(Transaction).filter(
            Transaction.timestamp >= target_date,
            Transaction.timestamp < next_date
        ).count()

        anomalies_detected = session.query(AnomalyDetection).filter(
            AnomalyDetection.detected_at >= target_date,
            AnomalyDetection.detected_at < next_date
        ).count()

        # Compute validation success rate: (non-flagged / total) * 100.
        # No transactions for the day -> None (honest empty state, not 100%).
        flagged_count = session.query(Transaction).filter(
            Transaction.timestamp >= target_date,
            Transaction.timestamp < next_date,
            Transaction.is_flagged == True
        ).count()
        validation_success_rate = (
            round(((total_transactions - flagged_count) / total_transactions) * 100, 2)
            if total_transactions > 0
            else None
        )

        # Average anomaly score for the day
        avg_score_result = session.query(AnomalyDetection).filter(
            AnomalyDetection.detected_at >= target_date,
            AnomalyDetection.detected_at < next_date
        ).with_entities(
            func.avg(AnomalyDetection.anomaly_score)
        ).scalar()
        avg_anomaly_score = round(float(avg_score_result or 0), 2)

        # Alert counts by severity
        critical_alerts = session.query(Alert).filter(
            Alert.created_at >= target_date,
            Alert.created_at < next_date,
            Alert.severity == SeverityLevel.CRITICAL
        ).count()

        high_alerts = session.query(Alert).filter(
            Alert.created_at >= target_date,
            Alert.created_at < next_date,
            Alert.severity == SeverityLevel.HIGH
        ).count()

    data = {
        "date": date_str,
        "total_transactions": total_transactions,
        "anomalies_detected": anomalies_detected,
        "validation_success_rate": validation_success_rate,
        "avg_anomaly_score": avg_anomaly_score,
        "critical_alerts": critical_alerts,
        "high_alerts": high_alerts
    }

    return jsonify(success_response(data, request_id)), 200

def _load_model_metrics(metrics_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load the real evaluation metrics written by ml/train_model.py
    (metrics_latest.json sits next to the trained model artifact).
    """
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

# Telemetry cache: a down node costs a 3s probe at most once per TTL window,
# instead of ~22s (retrying session) on every analytics request.
NODE_TELEMETRY_TTL_SECONDS = 30
_node_telemetry_cache: Dict[str, Any] = {"data": None, "fetched_at": 0.0}


def _probe_node_telemetry() -> Dict[str, Any]:
    """
    Single fast Tendermint /status probe (plain requests, no retry adapter,
    3s timeout). Never raises.
    """
    base = {
        "available": False,
        "online": False,
        "synced": False,
        "block_height": 0,
        "chain_id": qie_manager.chain_id,
        "rpc_url": qie_manager.rpc_url,
    }
    try:
        response = requests.post(
            qie_manager.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "status", "params": {}},
            timeout=3,
        )
        response.raise_for_status()
        result = response.json().get("result", {}) or {}
        sync_info = result.get("sync_info", {}) or {}
        return {
            **base,
            "available": True,
            "online": True,
            "synced": not bool(sync_info.get("catching_up", True)),
            "block_height": int(sync_info.get("latest_block_height", 0) or 0),
            "moniker": (result.get("node_info", {}) or {}).get("moniker", ""),
        }
    except Exception as exc:  # noqa: BLE001 — analytics must not fail on RPC
        logger.debug(f"Node telemetry probe failed: {exc}")
        return base


def _fetch_node_telemetry() -> Dict[str, Any]:
    """
    Live node telemetry for the analytics endpoints, cached for
    NODE_TELEMETRY_TTL_SECONDS. Never raises: when the QIE node is
    unreachable, returns available=False with neutral values so analytics
    still serve DB aggregates.
    """
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


@app.route("/api/v1/analytics/validator-stats", methods=["GET"])
@rate_limit
@require_auth
def get_validator_stats():
    """
    Validator stats from real sources only:
      - DB aggregates from the validators table (count, active, uptime, stake)
      - Per-validator transaction/alert counts joined on Transaction.sender
      - Live node telemetry (sync status, block height) with graceful fallback
    """
    request_id = generate_request_id()

    with db_manager.get_session() as session:
        total_validators = session.query(Validator).count()
        active_validators = session.query(Validator).filter(
            Validator.is_active == True
        ).count()
        avg_uptime_result = session.query(
            func.avg(Validator.uptime_percentage)
        ).scalar()
        total_staked_result = session.query(
            func.sum(Validator.stake_amount)
        ).scalar()
        transactions_total = session.query(Transaction).count()
        alerts_total = session.query(Alert).count()
        alerts_unresolved = session.query(Alert).filter(
            Alert.is_resolved == False
        ).count()

        top_validators_rows = session.query(Validator).order_by(
            Validator.stake_amount.desc()
        ).limit(5).all()
        total_stake = float(total_staked_result or 0)
        top_validators = []
        for v in top_validators_rows:
            stake = float(v.stake_amount or 0)
            voting_power = (
                round((stake / total_stake) * 100, 2) if total_stake > 0 else 0.0
            )
            # Per-validator counts: a QIE validator's own transactions use its
            # qie1... address as sender. Zero when it originated none.
            tx_count = session.query(Transaction).filter(
                Transaction.sender == v.address
            ).count()
            alert_count = session.query(Alert).join(
                Transaction, Alert.transaction_id == Transaction.id
            ).filter(
                Transaction.sender == v.address
            ).count()
            top_validators.append({
                "address": v.address,
                "name": v.name,
                "stake_amount": v.stake_amount,
                "voting_power": voting_power,
                "uptime": round(float(v.uptime_percentage or 0), 2),
                "is_active": v.is_active,
                "transactions": tx_count,
                "alerts": alert_count,
            })

    data = {
        "total_validators": total_validators,
        "active_validators": active_validators,
        "avg_uptime": round(float(avg_uptime_result or 0), 2),
        "total_staked": f"{round(float(total_staked_result or 0))} aqie",
        "transactions_total": transactions_total,
        "alerts_total": alerts_total,
        "alerts_unresolved": alerts_unresolved,
        "top_validators": top_validators,
        "node": _fetch_node_telemetry(),
    }
    return jsonify(success_response(data, request_id)), 200

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
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"

    logger.info(f"Starting ValiGuard AI API on port {port}")
    # socketio.run (not app.run) so the WebSocket feed is served too.
    socketio.run(app, host="0.0.0.0", port=port, debug=debug,
                 allow_unsafe_werkzeug=True)
