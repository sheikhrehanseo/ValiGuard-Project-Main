"""Stage 3 Socket.IO, commit-order, and persistence-parity tests."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sys

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

sys.path.insert(0, str(Path(__file__).parent))

from database.db import DatabaseConfig, DatabaseManager
from database.models import Alert, AnomalyDetection, Transaction
from test_alert_thresholds import FixedScoreModel


def _events(socket_client):
    return socket_client.get_received()


def _login(client):
    wallet = Account.create()
    nonce_response = client.post(
        "/api/v1/auth/request-nonce", json={"address": wallet.address}
    )
    nonce_data = nonce_response.get_json()["data"]
    signature = wallet.sign_message(
        encode_defunct(text=nonce_data["message"])
    ).signature.hex()
    verify_response = client.post(
        "/api/v1/auth/verify",
        json={
            "address": wallet.address,
            "nonce": nonce_data["nonce"],
            "signature": signature,
        },
    )
    return verify_response.get_json()["data"]["token"]


@pytest.fixture
def stage3_context(tmp_path, monkeypatch):
    import app as app_module

    database = DatabaseManager(
        DatabaseConfig(f"sqlite:///{tmp_path / 'stage3.db'}")
    )
    database.init_db()
    model = FixedScoreModel()
    monkeypatch.setattr(app_module, "db_manager", database)
    monkeypatch.setattr(app_module, "anomaly_model", model)
    return app_module, database, model


def test_scored_transaction_and_alert_emit_after_commit(stage3_context):
    app_module, database, model = stage3_context
    model.score_value = 45.0
    flask_client = app_module.app.test_client()
    socket_client = app_module.socketio.test_client(
        app_module.app, flask_test_client=flask_client
    )
    assert socket_client.is_connected()
    _events(socket_client)

    response = flask_client.post(
        "/api/v1/bridge/anomaly-score",
        json={"transaction_hash": "stage3-medium", "amount": 100.0},
    )
    assert response.status_code == 200

    received = _events(socket_client)
    transaction_event = next(item for item in received if item["name"] == "new_transaction")
    alert_event = next(item for item in received if item["name"] == "new_alert")
    transaction_payload = transaction_event["args"][0]
    alert_payload = alert_event["args"][0]

    with database.get_session() as session:
        transaction = session.query(Transaction).filter_by(
            tx_hash="stage3-medium"
        ).one()
        assert session.query(AnomalyDetection).filter_by(
            transaction_id=transaction.id
        ).count() == 1
        assert session.query(Alert).filter_by(
            transaction_id=transaction.id
        ).count() == 1

    assert transaction_payload["tx_hash"] == "stage3-medium"
    assert transaction_payload["value"] == 100.0
    assert transaction_payload["risk_score"] == 45.0
    assert transaction_payload["anomaly_score"] == 45.0
    assert transaction_payload["severity"] == "medium"
    assert transaction_payload["reason"] == "fixed test score 45.0"
    assert alert_payload["tx_hash"] == "stage3-medium"
    assert alert_payload["severity"] == "medium"
    assert alert_payload["reason"] == "fixed test score 45.0"


def test_low_score_emits_transaction_without_alert(stage3_context):
    app_module, _database, model = stage3_context
    model.score_value = 39.9
    flask_client = app_module.app.test_client()
    socket_client = app_module.socketio.test_client(
        app_module.app, flask_test_client=flask_client
    )
    _events(socket_client)

    response = flask_client.post(
        "/api/v1/bridge/anomaly-score",
        json={"transaction_hash": "stage3-low", "amount": 100.0},
    )
    assert response.status_code == 200

    received = _events(socket_client)
    names = [item["name"] for item in received]
    assert "new_transaction" in names
    assert "new_alert" not in names


def test_validate_cross_chain_uses_canonical_persistence(stage3_context):
    app_module, database, model = stage3_context
    model.score_value = 45.0
    response = app_module.app.test_client().post(
        "/api/v1/bridge/validate-cross-chain",
        json={
            "transaction_hash": "stage3-validate",
            "source_chain": "QIE",
            "dest_chain": "Ethereum",
            "amount": 100.0,
        },
    )
    assert response.status_code == 200
    with database.get_session() as session:
        transaction = session.query(Transaction).filter_by(
            tx_hash="stage3-validate"
        ).one()
        assert transaction.is_flagged is True
        assert session.query(AnomalyDetection).filter_by(
            transaction_id=transaction.id
        ).count() == 1
        assert session.query(Alert).filter_by(
            transaction_id=transaction.id
        ).count() == 1


def test_resolve_alert_emits_after_commit(stage3_context):
    app_module, database, model = stage3_context
    model.score_value = 45.0
    flask_client = app_module.app.test_client()
    socket_client = app_module.socketio.test_client(
        app_module.app, flask_test_client=flask_client
    )
    flask_client.post(
        "/api/v1/bridge/anomaly-score",
        json={"transaction_hash": "stage3-resolve", "amount": 100.0},
    )
    _events(socket_client)
    with database.get_session() as session:
        alert_id = session.query(Alert).one().id

    token = _login(flask_client)
    response = flask_client.patch(
        f"/api/v1/alerts/{alert_id}/resolve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    event = next(item for item in _events(socket_client) if item["name"] == "alert_resolved")
    assert event["args"][0]["alert_id"] == alert_id

    with database.get_session() as session:
        assert session.query(Alert).one().is_resolved is True


def test_alert_history_filters_reason_and_invalid_values(stage3_context):
    app_module, _database, model = stage3_context
    model.score_value = 45.0
    client = app_module.app.test_client()
    client.post(
        "/api/v1/bridge/anomaly-score",
        json={"transaction_hash": "stage3-history", "amount": 100.0},
    )
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(
        "/api/v1/alerts?severity=medium&resolved=false&tx_hash=stage3-history",
        headers=headers,
    )
    assert response.status_code == 200
    alert = response.get_json()["data"]["alerts"][0]
    assert alert["tx_hash"] == "stage3-history"
    assert alert["reason"] == "fixed test score 45.0"

    for query in (
        "?severity=info",
        "?resolved=maybe",
        "?from=not-a-date",
        "?from=2026-10-01&to=2026-09-01",
    ):
        invalid = client.get(f"/api/v1/alerts{query}", headers=headers)
        assert invalid.status_code == 400

    missing = client.patch("/api/v1/alerts/999999/resolve", headers=headers)
    assert missing.status_code == 404


def test_failed_commit_emits_no_events(stage3_context, monkeypatch):
    app_module, database, model = stage3_context
    model.score_value = 45.0
    flask_client = app_module.app.test_client()
    socket_client = app_module.socketio.test_client(
        app_module.app, flask_test_client=flask_client
    )
    _events(socket_client)

    class FailingDatabase:
        SessionLocal = database.SessionLocal

        @contextmanager
        def get_session(self):
            session = self.SessionLocal()
            try:
                yield session
                session.rollback()
                raise RuntimeError("forced commit failure")
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    monkeypatch.setattr(app_module, "db_manager", FailingDatabase())
    response = flask_client.post(
        "/api/v1/bridge/anomaly-score",
        json={"transaction_hash": "stage3-rollback", "amount": 100.0},
    )

    assert response.status_code == 400
    assert _events(socket_client) == []
    with database.get_session() as session:
        assert session.query(Transaction).filter_by(
            tx_hash="stage3-rollback"
        ).count() == 0
