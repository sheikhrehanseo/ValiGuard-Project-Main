"""Socket.IO event publisher for ValiGuard's live dashboard feed."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from flask import Flask
from flask_socketio import SocketIO, join_room

from core.severity import is_alerting_severity, severity_from_score


class SocketManager:
    """Own the Socket.IO transport and the dashboard event payload contract."""

    dashboard_room = "dashboard"

    def __init__(self, app: Flask) -> None:
        self.socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
        self.socketio.on_event("connect", self._on_connect)

    def _on_connect(self) -> None:
        """Subscribe each connected dashboard client to the live feed."""
        join_room(self.dashboard_room)

    def emit_transaction(self, transaction: Dict[str, Any]) -> None:
        """Publish a committed transaction and its anomaly/alert derivatives."""
        payload = self._transaction_payload(transaction)
        self.socketio.emit("new_transaction", payload, to=self.dashboard_room)

        if payload["anomaly_score"] is not None:
            self.socketio.emit("new_anomaly", self._anomaly_payload(payload), to=self.dashboard_room)

        if payload["is_flagged"] or is_alerting_severity(payload["severity"]):
            self.socketio.emit("new_alert", self._alert_payload(payload), to=self.dashboard_room)

    def emit_node_status(self, status: Dict[str, Any]) -> None:
        """Publish the latest node-health snapshot to dashboard clients."""
        self.socketio.emit("node_status", status, to=self.dashboard_room)

    def emit_alert_resolved(self, alert: Dict[str, Any]) -> None:
        """Publish a committed alert resolution."""
        self.socketio.emit("alert_resolved", alert, to=self.dashboard_room)

    @staticmethod
    def _transaction_payload(transaction: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = transaction.get("timestamp")
        anomaly_score = transaction.get("anomaly_score")
        severity = transaction.get("severity")
        if severity is None:
            severity = severity_from_score(anomaly_score) if anomaly_score is not None else "low"

        return {
            "tx_hash": transaction.get("tx_hash"),
            "value": transaction.get("value"),
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
            "tx_hash": transaction["tx_hash"],
            "severity": transaction["severity"],
            "anomaly_score": score,
            "risk_score": transaction["risk_score"],
            "reason": transaction["reason"],
            "message": f"Anomaly score {score_display} on {transaction['tx_hash']}",
            "timestamp": transaction["timestamp"],
        }
