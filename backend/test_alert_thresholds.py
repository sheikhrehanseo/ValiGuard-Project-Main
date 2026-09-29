"""Boundary tests for canonical Medium+ alerting behavior."""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent))

from core.severity import severity_from_score
from database.db import DatabaseConfig, DatabaseManager
from database.models import Alert, AnomalyDetection, Transaction
from ingestion.worker import IngestionWorker


class FixedScoreModel:
    """Deterministic scoring double for endpoint threshold tests."""

    def __init__(self):
        self.score_value = 0.0
        self.feature_extractor = self

    def get_feature_names(self):
        return []

    def score(self, transaction):
        severity = severity_from_score(self.score_value)
        return {
            "risk_score": self.score_value,
            "confidence": 90,
            "severity": severity,
            "reason": f"fixed test score {self.score_value}",
            "model_version": "test",
            "features": [],
        }


@pytest.fixture
def threshold_context(tmp_path, monkeypatch):
    import app as app_module

    database = DatabaseManager(
        DatabaseConfig(f"sqlite:///{tmp_path / 'thresholds.db'}")
    )
    database.init_db()
    model = FixedScoreModel()
    monkeypatch.setattr(app_module, "db_manager", database)
    monkeypatch.setattr(app_module, "anomaly_model", model)
    return app_module.app.test_client(), database, model


@pytest.mark.parametrize(
    ("score", "severity", "alerted"),
    [
        (39.9, "low", False),
        (40.0, "medium", True),
        (45.0, "medium", True),
        (85.0, "critical", True),
    ],
)
def test_score_boundary_persists_detection_and_alerts(
    threshold_context, score, severity, alerted
):
    client, database, model = threshold_context
    model.score_value = score
    tx_hash = f"0x{str(score).replace('.', ''):0>62}"[-64:]

    response = client.post(
        "/api/v1/bridge/anomaly-score",
        json={"transaction_hash": tx_hash, "amount": 100.0},
    )

    assert response.status_code == 200, response.get_json()
    with database.get_session() as session:
        transaction = session.query(Transaction).filter_by(tx_hash=tx_hash).one()
        detection = session.query(AnomalyDetection).filter_by(
            transaction_id=transaction.id
        ).one()
        alerts = session.query(Alert).filter_by(transaction_id=transaction.id).all()

        assert transaction.is_flagged is alerted
        assert detection.severity.value == severity
        assert len(alerts) == (1 if alerted else 0)
        if alerted:
            assert alerts[0].severity.value == severity


def test_manual_alert_rejects_noncanonical_severity():
    from app import AnomalyReportRequest

    with pytest.raises(ValidationError):
        AnomalyReportRequest(
            transaction_hash="0xmanual",
            severity="info",
            reason="invalid tier",
        )


@pytest.mark.parametrize(
    ("score", "severity", "alerted"),
    [(39.9, "low", False), (40.0, "medium", True), (45.0, "medium", True), (85.0, "critical", True)],
)
def test_worker_boundary_persists_canonical_alerts(
    threshold_context, score, severity, alerted
):
    _client, database, model = threshold_context
    model.score_value = score
    worker = IngestionWorker(
        node_manager=object(),
        db_manager=database,
        anomaly_model=model,
    )
    tx_hash = f"worker-{str(score).replace('.', '')}"

    result = worker._handle_raw({"hash": tx_hash, "_source": "block"})

    assert result is not None
    with database.get_session() as session:
        transaction = session.query(Transaction).filter_by(tx_hash=tx_hash).one()
        detection = session.query(AnomalyDetection).filter_by(
            transaction_id=transaction.id
        ).one()
        alerts = session.query(Alert).filter_by(transaction_id=transaction.id).all()

        assert transaction.is_flagged is alerted
        assert detection.severity.value == severity
        assert len(alerts) == (1 if alerted else 0)
