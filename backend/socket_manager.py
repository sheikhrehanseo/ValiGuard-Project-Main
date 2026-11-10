"""Socket.IO event publisher for ValiGuard's live dashboard feed."""

from __future__ import annotations

from datetime import datetime
import time
from threading import Lock
from typing import Any, Dict

from flask import Flask, request
from flask_socketio import SocketIO, join_room

from core.severity import is_alerting_severity, severity_from_score
from auth.jwt_auth import decode_token


class SocketManager:
    """Own the Socket.IO transport and the dashboard event payload contract."""

    dashboard_room = "dashboard"

    def __init__(self, app: Flask) -> None:
        self.socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
        self._sessions = {}
        self._lock = Lock()
        self.socketio.on_event("connect", self._on_connect)
        self.socketio.on_event("disconnect", self._on_disconnect)

    def _on_connect(self, auth=None):
        """Authenticate before admitting a client to protected telemetry."""
        token = auth.get("token") if isinstance(auth, dict) else None
        payload = decode_token(token) if isinstance(token, str) else None
        if payload is None or not payload.get("sub") or not payload.get("exp"):
            return False
        with self._lock:
            self._sessions[request.sid] = payload["exp"]
        join_room(self.dashboard_room)

    def _on_disconnect(self, reason=None):
        with self._lock:
            self._sessions.pop(request.sid, None)

    def _emit(self, event, payload, **kwargs):
        with self._lock:
            expired = [sid for sid, expiry in self._sessions.items() if expiry <= time.time()]
        for sid in expired:
            self.socketio.server.disconnect(sid, namespace="/")
        self.socketio.emit(event, payload, **kwargs)

    def emit_transaction(self, transaction: Dict[str, Any]) -> None:
        """Publish a committed transaction and its anomaly/alert derivatives."""
        payload = self._transaction_payload(transaction)
        self._emit("new_transaction", payload, to=self.dashboard_room)

        if payload["anomaly_score"] is not None and is_alerting_severity(payload["severity"]):
            self._emit("new_anomaly", self._anomaly_payload(payload), to=self.dashboard_room)

        if payload["alert_id"] is not None:
            if payload["is_resolved"]:
                self.emit_alert_resolved({
                    "alert_id": payload["alert_id"], "tx_hash": payload["tx_hash"],
                    "is_resolved": True, "resolved_at": payload["resolved_at"],
                })
            elif is_alerting_severity(payload["severity"]):
                self._emit("new_alert", self._alert_payload(payload), to=self.dashboard_room)

    def emit_node_status(self, status: Dict[str, Any]) -> None:
        """Publish the latest node-health snapshot to dashboard clients."""
        self._emit("node_status", status, to=self.dashboard_room)

    def emit_alert_resolved(self, alert: Dict[str, Any]) -> None:
        """Publish a committed alert resolution."""
        self._emit("alert_resolved", alert, to=self.dashboard_room)

    @staticmethod
    def _transaction_payload(transaction: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = transaction.get("timestamp")
        anomaly_score = transaction.get("anomaly_score")
        severity = transaction.get("severity")
        if severity is None:
            severity = severity_from_score(anomaly_score) if anomaly_score is not None else "low"

        return {
            "id": transaction.get("transaction_id", transaction.get("id")),
            "alert_id": transaction.get("alert_id"),
            "is_resolved": transaction.get("is_resolved", False),
            "resolved_at": transaction.get("resolved_at"),
            "alert_created_at": transaction.get("alert_created_at"),
            "tx_hash": transaction.get("tx_hash"),
            "value": transaction.get("value"),
            "asset_symbol": transaction.get("asset_symbol"),
            "asset_address": transaction.get("asset_address"),
            "is_update": transaction.get("is_update", False),
            "inference_latency_ms": transaction.get("inference_latency_ms"),
            "sender": transaction.get("sender"),
            "receiver": transaction.get("receiver"),
            "status": transaction.get("status"),
            "anomaly_score": anomaly_score,
            "risk_score": transaction.get("risk_score", anomaly_score),
            "is_flagged": transaction.get("is_flagged"),
            "raw_entry": transaction.get("raw_entry", transaction.get("sender") is None),
            "severity": severity,
            "reason": transaction.get("reason"),
            "source_chain": transaction.get("source_chain"),
            "destination_chain": transaction.get("destination_chain"),
            "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
        }

    @staticmethod
    def _anomaly_payload(transaction: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "tx_hash": transaction["tx_hash"],
            "anomaly_score": transaction["anomaly_score"],
            "risk_score": transaction["risk_score"],
            "severity": transaction["severity"],
            "reason": transaction["reason"],
            "timestamp": transaction["timestamp"],
        }

    @staticmethod
    def _alert_payload(transaction: Dict[str, Any]) -> Dict[str, Any]:
        score = transaction["anomaly_score"]
        score_display = f"{float(score):.1f}" if score is not None else "unavailable"
        return {
            "id": transaction.get("alert_id"),
            "alert_id": transaction.get("alert_id"),
            "tx_hash": transaction["tx_hash"],
            "severity": transaction["severity"],
            "anomaly_score": score,
            "risk_score": transaction["risk_score"],
            "reason": transaction["reason"],
            "message": f"Anomaly score {score_display} on {transaction['tx_hash']}",
            "is_resolved": transaction["is_resolved"],
            "timestamp": transaction.get("alert_created_at") or transaction["timestamp"],
        }
