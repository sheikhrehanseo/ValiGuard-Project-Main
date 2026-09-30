"""Canonical transaction scoring and persistence shared by all entry points."""

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional

from core.severity import is_alerting_severity, severity_from_score
from database.models import (
    Alert,
    AlertType,
    AnomalyDetection,
    Bridge,
    SeverityLevel,
    Transaction,
    TransactionStatus,
)


def _severity_enum(value: str) -> SeverityLevel:
    return SeverityLevel(str(value).lower())


def score_and_persist_transaction(
    *,
    session,
    anomaly_model,
    tx_hash: str,
    source_chain: Optional[str],
    destination_chain: Optional[str],
    value: Optional[float],
    sender: Optional[str],
    receiver: Optional[str],
    timestamp: datetime,
    status: TransactionStatus = TransactionStatus.PENDING,
    bridge_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Score and persist one transaction inside the caller's DB session.

    The caller owns the transaction. Events must be emitted only after the
    caller's session context exits successfully and commits.
    """
    scoring_transaction = SimpleNamespace(
        value=float(value) if value is not None else 0.0,
        sender=sender,
        receiver=receiver,
        timestamp=timestamp,
        tx_hash=tx_hash,
    )
    score_result = anomaly_model.score(scoring_transaction)
    model_unavailable = bool(
        score_result.get("model_unavailable")
        or score_result.get("risk_score") is None
    )
    if model_unavailable:
        severity = "low"
        flagged = False
        risk_score = None
    else:
        risk_score = float(score_result["risk_score"])
        severity = severity_from_score(risk_score)
        flagged = is_alerting_severity(severity)

    transaction = session.query(Transaction).filter_by(tx_hash=tx_hash).first()
    if transaction is None:
        if bridge_id is None and (sender or receiver):
            known_addresses = [address for address in (sender, receiver) if address]
            bridge = session.query(Bridge).filter(
                Bridge.address.in_(known_addresses)
            ).first()
            bridge_id = bridge.id if bridge else None
        transaction = Transaction(
            tx_hash=tx_hash,
            bridge_id=bridge_id,
            source_chain=source_chain,
            destination_chain=destination_chain,
            value=value,
            sender=sender,
            receiver=receiver,
            timestamp=timestamp,
            status=status,
        )
        session.add(transaction)
        session.flush()
    else:
        transaction.anomaly_score = risk_score
        transaction.is_flagged = flagged
        transaction.status = status
        session.flush()

    transaction.anomaly_score = risk_score
    transaction.is_flagged = flagged

    if model_unavailable:
        session.flush()
        unavailable_reason = "model_unavailable"
        if sender is None:
            unavailable_reason += "; raw entry (volume unavailable)"
        unavailable_score = dict(score_result)
        unavailable_score.update({
            "risk_score": None,
            "severity": severity,
            "reason": unavailable_reason,
            "model_unavailable": True,
        })
        return {
            "transaction": transaction,
            "detection": None,
            "alert": None,
            "score": unavailable_score,
        }

    feature_names = (
        anomaly_model.feature_extractor.get_feature_names()
        if getattr(anomaly_model, "feature_extractor", None)
        else []
    )
    features = score_result.get("features") or []
    features_used = {
        name: float(feature_value)
        for name, feature_value in zip(feature_names, features)
    }
    raw_entry = sender is None
    features_used["volume_available"] = value is not None
    features_used["sender_available"] = sender is not None
    features_used["receiver_available"] = receiver is not None
    features_used["chains_available"] = (
        source_chain is not None and destination_chain is not None
    )
    reason = score_result.get("reason")
    if raw_entry:
        marker = "raw entry (volume unavailable)"
        reason = f"{reason}; {marker}" if reason else marker
    detection = AnomalyDetection(
        transaction_id=transaction.id,
        anomaly_score=risk_score,
        confidence=float(score_result.get("confidence", 0)),
        features_used=features_used,
        model_version=str(score_result.get("model_version", "unknown")),
        severity=_severity_enum(severity),
        reason=reason,
    )
    session.add(detection)

    alert = None
    if flagged:
        alert = Alert(
            transaction_id=transaction.id,
            alert_type=AlertType.ANOMALY,
            severity=_severity_enum(severity),
            message=(
                f"Anomaly score {risk_score:.2f} ({severity}): "
                f"{score_result.get('reason', 'flagged by ML model')}"
            ),
        )
        session.add(alert)

    session.flush()
    canonical_score = dict(score_result)
    canonical_score.update({
        "risk_score": risk_score,
        "severity": severity,
        "reason": reason,
    })
    return {
        "transaction": transaction,
        "detection": detection,
        "alert": alert,
        "score": canonical_score,
    }
