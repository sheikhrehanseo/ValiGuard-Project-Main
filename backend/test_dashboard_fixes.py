"""Behavioral checks for open anomalies, alert lifecycle, and amount units."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from database.models import Alert, AlertType, AnomalyDetection, SeverityLevel, Transaction, TransactionStatus
from ingestion.worker import IngestionWorker, _coerce_float
from test_audit_regressions import context
from test_alert_thresholds import FixedScoreModel


def seed_alert(session, name, score, created, resolved=False):
    severity = SeverityLevel.CRITICAL if score >= 80 else SeverityLevel.HIGH if score >= 60 else SeverityLevel.MEDIUM if score >= 40 else SeverityLevel.LOW
    tx = Transaction(tx_hash=name, timestamp=created, anomaly_score=score,
                     is_flagged=score >= 40, status=TransactionStatus.CONFIRMED)
    session.add(tx)
    session.flush()
    session.add(AnomalyDetection(transaction_id=tx.id, anomaly_score=score, confidence=90,
                                 model_version="test", severity=severity, detected_at=created))
    alert = Alert(transaction_id=tx.id, alert_type=AlertType.ANOMALY, severity=severity,
                  message=name, created_at=created, is_resolved=resolved)
    session.add(alert)
    session.flush()
    return alert.id


def test_rolling_open_count_and_single_bulk_resolution(context, monkeypatch):
    app, db, headers = context
    now = datetime(2026, 11, 11, 1)
    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return now
    monkeypatch.setattr(app, "datetime", Clock)
    with db.get_session() as session:
        ids = [seed_alert(session, "medium", 40, now - timedelta(hours=23)),
               seed_alert(session, "high", 60, now - timedelta(hours=1)),
               seed_alert(session, "critical", 80, now)]
        seed_alert(session, "normal", 10, now)
        seed_alert(session, "resolved", 90, now, resolved=True)
        seed_alert(session, "too-old", 90, now - timedelta(hours=24, microseconds=1))
        seed_alert(session, "future", 90, now + timedelta(seconds=1))
    client = app.app.test_client()
    def count():
        response = client.get("/api/v1/analytics/open-anomalies", headers=headers)
        assert response.status_code == 200
        return response.json["data"]["open_anomalies_24h"]
    assert count() == 3  # Includes yesterday, excludes Low/resolved/expired/future.
    assert client.patch(f"/api/v1/alerts/{ids[0]}/resolve", headers=headers).status_code == 200
    assert count() == 2
    client.patch(f"/api/v1/alerts/{ids[0]}/resolve", headers=headers)
    assert count() == 2
    client.post("/api/v1/alerts/resolve-bulk", json={"alert_ids": ids[1:]}, headers=headers)
    assert count() == 0
    history = client.get("/api/v1/alerts?resolved=true", headers=headers).json["data"]
    assert set(ids).issubset({alert["id"] for alert in history["alerts"]})


def test_normal_scores_are_not_anomalies_and_unscored_are_not_low_risk(context):
    app, db, headers = context
    now = datetime.utcnow()
    with db.get_session() as session:
        seed_alert(session, "normal", 10, now)
        seed_alert(session, "high", 70, now)
        session.add(Transaction(tx_hash="unscored", timestamp=now, anomaly_score=None, is_flagged=False))
    data = app.app.test_client().get("/api/v1/analytics/daily-stats", headers=headers).json["data"]
    assert data["anomalies_detected"] == 1
    assert data["open_anomalies_24h"] == 1
    assert data["scored_transactions"] == 2
    assert data["low_risk_rate"] == 50


@pytest.mark.parametrize("resolve_first,confirmed_score", [(True, 85), (False, 10)])
def test_confirmation_does_not_reopen_or_duplicate_alerts(context, monkeypatch, resolve_first, confirmed_score):
    app, db, headers = context
    model = FixedScoreModel()
    model.score_value = 85
    events = []
    monkeypatch.setattr(app.socket_manager, "_emit", lambda name, payload, **kwargs: events.append((name, payload)))
    worker = IngestionWorker(node_manager=SimpleNamespace(), db_manager=db, anomaly_model=model,
                             on_new_transaction=app._emit_transaction_events)
    tx = {"hash": "pending-confirmed", "sender": "sender", "value": 1}
    pending = worker.process_raw_transaction({**tx, "status": "pending"})
    if resolve_first:
        app.app.test_client().patch(f"/api/v1/alerts/{pending['alert_id']}/resolve", headers=headers)
    events.clear()
    model.score_value = confirmed_score
    worker.process_raw_transaction({**tx, "status": "confirmed", "height": 1})
    assert "new_alert" not in [name for name, _ in events]
    assert "alert_resolved" in [name for name, _ in events]
    with db.get_session() as session:
        assert session.query(Alert).count() == 1
        assert session.query(Alert).one().is_resolved
        assert session.query(Alert).one().resolved_at is not None
    assert app.app.test_client().get("/api/v1/analytics/open-anomalies", headers=headers).json["data"]["open_anomalies_24h"] == 0
    events.clear()
    assert worker.process_raw_transaction({**tx, "status": "confirmed", "height": 1}) is None
    assert not events


def test_all_alert_history_pages_are_accessible(context):
    app, db, headers = context
    now = datetime.utcnow()
    with db.get_session() as session:
        for i in range(53):
            seed_alert(session, f"page-{i}", 60, now)
    client = app.app.test_client()
    pages = [client.get(f"/api/v1/alerts?limit=50&offset={offset}", headers=headers).json["data"] for offset in (0, 50)]
    assert [len(page["alerts"]) for page in pages] == [50, 3]
    assert len({alert["id"] for page in pages for alert in page["alerts"]}) == 53
    assert all(page["total"] == 53 for page in pages)


@pytest.mark.parametrize("raw,expected", [
    ({"amount": "500000", "denom": "uqie"}, 0.5),
    ({"amount": "1", "denom": "aqie"}, 1e-18),
    ("500000uqie", 0.5), ("1wei", 1e-18), ("0x1", 1e-18),
    ("0x0", 0), ("2qie", 2), (2, 2),
])
def test_units_do_not_depend_on_amount_size(raw, expected):
    assert _coerce_float(raw) == pytest.approx(expected, rel=1e-12, abs=0)
