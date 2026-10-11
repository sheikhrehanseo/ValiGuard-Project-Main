"""Stage 4.1 re-score idempotency, model-unavailable preservation, and bridge-fallback removal tests."""

from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from core.scoring import score_and_persist_transaction
from database.db import DatabaseConfig, DatabaseManager
from database.models import (
    Alert,
    AlertType,
    AnomalyDetection,
    Bridge,
    SeverityLevel,
    Transaction,
    TransactionStatus,
)
from test_alert_thresholds import FixedScoreModel


class ConfigurableModel:
    def __init__(self, score_value=45.0, reason="test score", model_unavailable=False):
        self.score_value = score_value
        self.reason = reason
        self.model_unavailable = model_unavailable
        self.feature_extractor = self

    def get_feature_names(self):
        return ["feat_a", "feat_b"]

    def score(self, transaction):
        if self.model_unavailable:
            return {
                "risk_score": None,
                "confidence": 0,
                "severity": "low",
                "reason": "model_unavailable",
                "model_version": "fallback",
                "features": [],
                "model_unavailable": True,
            }
        from core.severity import severity_from_score
        severity = severity_from_score(self.score_value)
        return {
            "risk_score": self.score_value,
            "confidence": 88.0,
            "severity": severity,
            "reason": self.reason,
            "model_version": "v1.0",
            "features": [1.0, 2.0],
        }


@pytest.fixture
def scoring_db(tmp_path):
    db = DatabaseManager(DatabaseConfig(f"sqlite:///{tmp_path / 'scoring_test.db'}"))
    db.init_db()
    return db


def test_pending_to_confirmed_rescore_idempotent(scoring_db):
    """Pending 45 -> confirmed 45: exactly ONE detection and ONE alert row, updated in place."""
    model = ConfigurableModel(score_value=45.0, reason="initial pending score")
    tx_hash = "0xrescore01"

    # 1. Initial pending score
    with scoring_db.get_session() as session:
        res1 = score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=100.0,
            sender="0xsender1",
            receiver="0xreceiver1",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.PENDING,
        )
        tx1_id = res1["transaction"].id
        det1_id = res1["detection"].id
        alt1_id = res1["alert"].id

    with scoring_db.get_session() as session:
        assert session.query(Transaction).count() == 1
        assert session.query(AnomalyDetection).count() == 1
        assert session.query(Alert).count() == 1
        det = session.query(AnomalyDetection).one()
        assert det.anomaly_score == 45.0
        assert det.reason == "initial pending score"
        alt = session.query(Alert).one()
        assert alt.severity == SeverityLevel.MEDIUM
        assert not alt.is_resolved

    # 2. Re-score as confirmed
    model.reason = "confirmed re-score evaluation"
    with scoring_db.get_session() as session:
        res2 = score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=100.0,
            sender="0xsender1",
            receiver="0xreceiver1",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.CONFIRMED,
        )
        assert res2["transaction"].id == tx1_id
        assert res2["detection"].id == det1_id
        assert res2["alert"].id == alt1_id

    # Verify exactly one detection and one alert exist, updated on the same rows
    with scoring_db.get_session() as session:
        assert session.query(Transaction).count() == 1
        tx = session.query(Transaction).one()
        assert tx.status == TransactionStatus.CONFIRMED

        assert session.query(AnomalyDetection).count() == 1
        det = session.query(AnomalyDetection).one()
        assert det.id == det1_id
        assert det.reason == "confirmed re-score evaluation"

        assert session.query(Alert).count() == 1
        alt = session.query(Alert).one()
        assert alt.id == alt1_id
        assert alt.severity == SeverityLevel.MEDIUM


def test_severity_change_rescore_updates_same_alert_row(scoring_db):
    """Severity change 45 -> 85 on re-score: the SAME alert row is updated to critical, no second row."""
    model = ConfigurableModel(score_value=45.0, reason="medium anomaly")
    tx_hash = "0xseverity_escalate"

    with scoring_db.get_session() as session:
        score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=50.0,
            sender="0xsender2",
            receiver="0xreceiver2",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.PENDING,
        )

    with scoring_db.get_session() as session:
        alt = session.query(Alert).one()
        alt_id = alt.id
        assert alt.severity == SeverityLevel.MEDIUM

    # Escalation to 85.0
    model.score_value = 85.0
    model.reason = "critical breach detected"
    with scoring_db.get_session() as session:
        score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=50.0,
            sender="0xsender2",
            receiver="0xreceiver2",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.CONFIRMED,
        )

    with scoring_db.get_session() as session:
        assert session.query(Alert).count() == 1
        alt = session.query(Alert).one()
        assert alt.id == alt_id
        assert alt.severity == SeverityLevel.CRITICAL
        assert "85.00" in alt.message
        assert "critical breach detected" in alt.message


def test_resolved_alert_rescore_creates_no_new_alert(scoring_db):
    """Resolved alert + re-score: no new alert created."""
    model = ConfigurableModel(score_value=45.0, reason="alert to resolve")
    tx_hash = "0xresolved_alert"

    with scoring_db.get_session() as session:
        score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=50.0,
            sender="0xsender3",
            receiver="0xreceiver3",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.PENDING,
        )

    # Operator marks alert as resolved
    with scoring_db.get_session() as session:
        alt = session.query(Alert).one()
        alt.is_resolved = True
        alt.resolved_at = datetime.utcnow()
        session.commit()

    # Re-score with critical score 85.0
    model.score_value = 85.0
    model.reason = "critical new score"
    with scoring_db.get_session() as session:
        res = score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=50.0,
            sender="0xsender3",
            receiver="0xreceiver3",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.CONFIRMED,
        )
        assert res["alert"] is None

    # Verify no second alert row was added and existing alert is still resolved
    with scoring_db.get_session() as session:
        alerts = session.query(Alert).all()
        assert len(alerts) == 1
        assert alerts[0].is_resolved is True


def test_model_unavailable_rescore_preserves_valid_score(scoring_db):
    """Model-unavailable re-score: prior valid score and is_flagged preserved, no NULL clobber."""
    model = ConfigurableModel(score_value=45.0, reason="valid ml score")
    tx_hash = "0xmodel_unavailable_rescore"

    with scoring_db.get_session() as session:
        score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=50.0,
            sender="0xsender4",
            receiver="0xreceiver4",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.PENDING,
        )

    with scoring_db.get_session() as session:
        tx = session.query(Transaction).one()
        assert tx.anomaly_score == 45.0
        assert tx.is_flagged is True
        assert session.query(AnomalyDetection).count() == 1
        assert session.query(Alert).count() == 1

    # Re-score with model unavailable
    model.model_unavailable = True
    with scoring_db.get_session() as session:
        res = score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=50.0,
            sender="0xsender4",
            receiver="0xreceiver4",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.CONFIRMED,
        )
        assert res["score"]["risk_score"] == 45.0
        assert res["score"]["model_unavailable"] is True

    # Check that Transaction anomaly_score was NOT overwritten with None
    with scoring_db.get_session() as session:
        tx = session.query(Transaction).one()
        assert tx.status == TransactionStatus.CONFIRMED
        assert tx.anomaly_score == 45.0
        assert tx.is_flagged is True
        # Detection and alert rows are preserved
        assert session.query(AnomalyDetection).count() == 1
        assert session.query(Alert).count() == 1


def test_raw_entry_bridge_id_stays_null_and_no_default_bridge(scoring_db):
    """Raw entry: bridge_id stays NULL; no 'bridge:*:default' row exists."""
    model = ConfigurableModel(score_value=30.0, reason="raw entry test")
    tx_hash = "0xraw_entry_null_bridge"

    with scoring_db.get_session() as session:
        score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain=None,
            destination_chain=None,
            value=None,
            sender=None,
            receiver=None,
            timestamp=datetime.utcnow(),
            status=TransactionStatus.PENDING,
        )

    with scoring_db.get_session() as session:
        tx = session.query(Transaction).one()
        assert tx.bridge_id is None
        assert tx.sender is None
        assert tx.receiver is None
        # Check bridges table has 0 default bridges
        default_bridges = session.query(Bridge).filter(
            Bridge.address.like("bridge:%:default")
        ).all()
        assert len(default_bridges) == 0


def test_reason_and_alert_message_capped_at_500_chars(scoring_db):
    """Detection reason and alert message have 500-char caps with ellipsis."""
    oversized_reason = "X" * 600
    model = ConfigurableModel(score_value=50.0, reason=oversized_reason)
    tx_hash = "0xoversized_reason"

    with scoring_db.get_session() as session:
        score_and_persist_transaction(
            session=session,
            anomaly_model=model,
            tx_hash=tx_hash,
            source_chain="QIE",
            destination_chain="Ethereum",
            value=100.0,
            sender="0xsender5",
            receiver="0xreceiver5",
            timestamp=datetime.utcnow(),
            status=TransactionStatus.PENDING,
        )

    with scoring_db.get_session() as session:
        det = session.query(AnomalyDetection).one()
        assert len(det.reason) == 500
        assert det.reason.endswith("...")

        alt = session.query(Alert).one()
        assert len(alt.message) == 500
        assert alt.message.endswith("...")


def test_rescore_commit_does_not_emit_duplicate_socket_events(tmp_path, monkeypatch):
    """Re-score commit does not emit duplicate socket events."""
    import app as app_module
    from ingestion.worker import IngestionWorker

    database = DatabaseManager(DatabaseConfig(f"sqlite:///{tmp_path / 'ws_rescore.db'}"))
    database.init_db()
    model = ConfigurableModel(score_value=45.0, reason="socket rescore test")

    worker = IngestionWorker(
        db_manager=database,
        anomaly_model=model,
        on_new_transaction=app_module._emit_transaction_events,
    )
    monkeypatch.setattr(app_module, "db_manager", database)
    monkeypatch.setattr(app_module, "anomaly_model", model)
    monkeypatch.setattr(app_module, "ingestion_worker", worker)

    flask_client = app_module.app.test_client()
    socket_client = app_module.socketio.test_client(
        app_module.app, flask_test_client=flask_client
    )
    assert socket_client.is_connected()
    socket_client.get_received()  # drain initial events

    # 1. First submission: pending tx from mempool
    res1 = worker._handle_raw({
        "hash": "tx-socket-rescore",
        "_source": "mempool",
        "value": 100.0,
    })
    assert res1 is not None
    events1 = socket_client.get_received()
    event_names1 = [e["name"] for e in events1]
    assert event_names1 == ["new_transaction", "new_anomaly", "new_alert"]

    # 2. Second submission: re-score on block confirmation (severity changed to critical 85.0)
    model.score_value = 85.0
    res2 = worker._handle_raw({
        "hash": "tx-socket-rescore",
        "_source": "block",
        "height": 1234,
        "value": 100.0,
    })
    assert res2 is not None
    events2 = socket_client.get_received()
    event_names2 = [e["name"] for e in events2]
    # Exactly one new_transaction, one new_anomaly, one new_alert emitted for the re-score
    assert event_names2 == ["new_transaction", "new_anomaly", "new_alert"]

    # In database, exactly one transaction, one detection, and one alert row
    with database.get_session() as session:
        assert session.query(Transaction).count() == 1
        tx = session.query(Transaction).one()
        assert tx.status == TransactionStatus.CONFIRMED
        assert tx.anomaly_score == 85.0
        assert session.query(AnomalyDetection).count() == 1
        assert session.query(Alert).count() == 1
        alt = session.query(Alert).one()
        assert alt.severity == SeverityLevel.CRITICAL
