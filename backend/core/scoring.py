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


def _truncate_text(text: Optional[str], max_len: int = 500) -> Optional[str]:
    """Cap text at max_len (default 500), truncating with an ellipsis if needed."""
    if text is None or len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


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

    Re-score semantics & idempotency:
    - Transaction: If an existing transaction exists for `tx_hash`, its status
      is updated. If a valid score is available, `anomaly_score` and `is_flagged`
      are updated. If the model is unavailable on re-score, the prior valid
      `anomaly_score` and `is_flagged` are preserved (never overwritten with NULL/False).
    - AnomalyDetection: Exactly one row per transaction, ever. On re-score, the
      existing row is updated in place (score, confidence, features_used, model_version,
      severity, reason). The latest evaluation is authoritative; intermediate score
      history is not retained.
    - Alert: If an UNRESOLVED alert exists for the transaction, its severity and
      message are updated in place (escalation or de-escalation). If the existing
      alert is RESOLVED, create NO new alert — the operator has already acted.
      Never append a second alert row.
    - Reason & Message truncation: Detection reason and alert message are capped
      at 500 characters, truncating with an ellipsis ('...') if longer, to prevent
      PostgreSQL write rejections.
    - Bridge association: `bridge_id` is set ONLY on a real sender/receiver address
      match against known bridges, or NULL otherwise. Synthetic default bridge rows
      are never created.
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

    transaction = session.query(Transaction).filter_by(tx_hash=tx_hash).first()

    if model_unavailable:
        # Check if this is a re-score of a transaction with an existing valid score
        if transaction is not None and transaction.anomaly_score is not None:
            # Preserve the previous valid score and is_flagged
            risk_score = transaction.anomaly_score
            flagged = transaction.is_flagged
            severity = severity_from_score(risk_score)
            transaction.status = status
            session.flush()

            existing_detection = session.query(AnomalyDetection).filter_by(
                transaction_id=transaction.id
            ).first()
            existing_alert = session.query(Alert).filter_by(
                transaction_id=transaction.id
            ).first()

            unavailable_score = dict(score_result)
            unavailable_score.update({
                "risk_score": risk_score,
                "severity": severity,
                "reason": existing_detection.reason if existing_detection else score_result.get("reason"),
                "model_unavailable": True,
            })
            return {
                "transaction": transaction,
                "detection": existing_detection,
                "alert": existing_alert,
                "score": unavailable_score,
            }

        # Model unavailable on first-time scoring (or tx had no prior score)
        severity = "low"
        flagged = False
        risk_score = None
        if transaction is None:
            if bridge_id is None and (sender or receiver):
                known_addresses = [a for a in (sender, receiver) if a]
                bridge = session.query(Bridge).filter(
                    Bridge.address.in_(known_addresses)
                ).first()
                bridge_id = bridge.id if bridge is not None else None
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
            transaction.anomaly_score = None
            transaction.is_flagged = False
        else:
            transaction.status = status
            if transaction.anomaly_score is None:
                transaction.anomaly_score = None
                transaction.is_flagged = False

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

    # Model is available
    risk_score = float(score_result["risk_score"])
    severity = severity_from_score(risk_score)
    flagged = is_alerting_severity(severity)

    if transaction is None:
        if bridge_id is None and (sender or receiver):
            known_addresses = [a for a in (sender, receiver) if a]
            bridge = session.query(Bridge).filter(
                Bridge.address.in_(known_addresses)
            ).first()
            bridge_id = bridge.id if bridge is not None else None
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
            anomaly_score=risk_score,
            is_flagged=flagged,
        )
        session.add(transaction)
    else:
        transaction.anomaly_score = risk_score
        transaction.is_flagged = flagged
        transaction.status = status

    session.flush()

    # Feature extraction & reason preparation
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
    reason = _truncate_text(reason, 500)

    # AnomalyDetection: exactly one row per transaction, ever.
    detection = session.query(AnomalyDetection).filter_by(
        transaction_id=transaction.id
    ).first()
    if detection is None:
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
    else:
        detection.anomaly_score = risk_score
        detection.confidence = float(score_result.get("confidence", 0))
        detection.features_used = features_used
        detection.model_version = str(score_result.get("model_version", "unknown"))
        detection.severity = _severity_enum(severity)
        detection.reason = reason

    # Alert handling:
    # If an UNRESOLVED alert exists for the tx, UPDATE its severity/message in place
    # (escalation or de-escalation). If the existing alert is RESOLVED, create NO new
    # alert — the operator has already acted. Never append a second alert row.
    raw_alert_message = (
        f"Anomaly score {risk_score:.2f} ({severity}): "
        f"{score_result.get('reason', 'flagged by ML model')}"
    )
    alert_message = _truncate_text(raw_alert_message, 500)

    existing_alert = session.query(Alert).filter_by(
        transaction_id=transaction.id
    ).first()

    alert = None
    if existing_alert is not None:
        if not existing_alert.is_resolved:
            existing_alert.severity = _severity_enum(severity)
            existing_alert.message = alert_message
            alert = existing_alert
        else:
            # Resolved alert: operator has already acted. Create NO new alert.
            alert = None
    elif flagged:
        alert = Alert(
            transaction_id=transaction.id,
            alert_type=AlertType.ANOMALY,
            severity=_severity_enum(severity),
            message=alert_message,
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
