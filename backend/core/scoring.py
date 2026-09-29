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
    BridgeStatus,
    SeverityLevel,
    Transaction,
    TransactionStatus,
)


def _severity_enum(value: str) -> SeverityLevel:
    return SeverityLevel(str(value).lower())


def _get_or_create_bridge(session, chain_name: str) -> Bridge:
    address = f"bridge:{(chain_name or 'QIE').lower()}:default"
    bridge = session.query(Bridge).filter_by(address=address).first()
    if bridge is None:
        bridge = Bridge(
            address=address,
            chain_name=chain_name or "QIE",
            status=BridgeStatus.ACTIVE,
        )
        session.add(bridge)
        session.flush()
    return bridge


def score_and_persist_transaction(
    *,
    session,
    anomaly_model,
    tx_hash: str,
    source_chain: str,
    destination_chain: str,
    value: float,
    sender: str,
    receiver: str,
    timestamp: datetime,
    status: TransactionStatus = TransactionStatus.PENDING,
    bridge_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Score and persist one transaction inside the caller's DB session.

    The caller owns the transaction. Events must be emitted only after the
    caller's session context exits successfully and commits.
    """
    scoring_transaction = SimpleNamespace(
        value=float(value),
        sender=sender,
        receiver=receiver,
        timestamp=timestamp,
        tx_hash=tx_hash,
    )
    score_result = anomaly_model.score(scoring_transaction)
    risk_score = float(score_result["risk_score"])
    severity = severity_from_score(risk_score)
    flagged = is_alerting_severity(severity)

    transaction = session.query(Transaction).filter_by(tx_hash=tx_hash).first()
    if transaction is None:
        if bridge_id is None:
            bridge_id = _get_or_create_bridge(session, source_chain).id
        transaction = Transaction(
            tx_hash=tx_hash,
            bridge_id=bridge_id,
            source_chain=source_chain,
            destination_chain=destination_chain,
            value=float(value),
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
    detection = AnomalyDetection(
        transaction_id=transaction.id,
        anomaly_score=risk_score,
        confidence=float(score_result.get("confidence", 0)),
        features_used=features_used,
        model_version=str(score_result.get("model_version", "unknown")),
        severity=_severity_enum(severity),
        reason=score_result.get("reason"),
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
        "reason": score_result.get("reason"),
    })
    return {
        "transaction": transaction,
        "detection": detection,
        "alert": alert,
        "score": canonical_score,
    }
