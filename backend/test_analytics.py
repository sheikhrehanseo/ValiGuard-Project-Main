"""
Tests for the analytics endpoints (real-analytics stage).

Covers:
  - Seeded DB -> both endpoints return the real seeded values (aggregates,
    per-validator tx/alert counts, stake-based voting power).
  - Empty DB -> honest empty states, never fabricated numbers.
  - Missing metrics file -> honest error state with None metrics.
  - 401 without a token on both analytics endpoints.

The test DB is an isolated temp SQLite file (DATABASE_URL is set before the
app module is imported, since the app binds its DatabaseManager at import
time). A guard skips the truncating fixtures if the app somehow got bound
to a different DB — truncation must never touch the developer's valiguard.db.
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# --- isolated test DB + no ingestion worker: BEFORE importing the app ---
_TEST_DB = os.path.join(tempfile.gettempdir(), "valiguard_test_analytics.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("VALIGUARD_INGESTION_WORKER", "0")

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))          # project root (backend.* imports)
sys.path.insert(0, str(Path(__file__).parent))  # backend/ (database imports)

import pytest  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

import app as flask_app_module  # noqa: E402
from database.models import (  # noqa: E402
    Alert,
    AlertType,
    AnomalyDetection,
    Bridge,
    BridgeStatus,
    SeverityLevel,
    Transaction,
    TransactionStatus,
    Validator,
)


@pytest.fixture(scope="module", autouse=True)
def ensure_test_db():
    """Refuse to truncate anything that is not the dedicated test DB."""
    url = flask_app_module.db_manager.config.db_url.replace("\\", "/")
    if _TEST_DB.replace("\\", "/") not in url:
        pytest.skip(
            "app bound to a non-test database "
            f"({url}); run test_analytics.py first in the suite"
        )
    # Clean slate for the whole module.
    _truncate_all_tables()


def _truncate_all_tables():
    with flask_app_module.db_manager.get_session() as session:
        for model in (Alert, AnomalyDetection, Transaction, Validator, Bridge):
            session.query(model).delete()


@pytest.fixture(scope="module")
def client():
    return flask_app_module.app.test_client()


@pytest.fixture(scope="module")
def token(client):
    """JWT obtained via the real nonce -> sign -> verify flow."""
    wallet = Account.create()
    r = client.post("/api/v1/auth/request-nonce", json={"address": wallet.address})
    assert r.status_code == 200
    data = r.get_json()["data"]
    signed = wallet.sign_message(encode_defunct(text=data["message"]))
    sig = signed.signature.hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"
    r = client.post("/api/v1/auth/verify", json={
        "address": wallet.address,
        "nonce": data["nonce"],
        "signature": sig,
    })
    assert r.status_code == 200
    return r.get_json()["data"]["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_known_data():
    """
    Insert rows with known values. Expected aggregates:
      validators: 3 total, 2 active, avg uptime 96.0, total stake 6000
      v1 (top by stake): voting power 66.67, 2 txs, 1 alert
    """
    with flask_app_module.db_manager.get_session() as session:
        bridge = Bridge(address="0xbridge-analytics", chain_name="QIE",
                        status=BridgeStatus.ACTIVE)
        session.add(bridge)
        session.flush()

        v1 = Validator(address="qie1valone", name="V-One",
                       stake_amount=4000.0, uptime_percentage=99.0, is_active=True)
        v2 = Validator(address="qie1valtwo", name="V-Two",
                       stake_amount=1000.0, uptime_percentage=97.0, is_active=True)
        v3 = Validator(address="qie1valthree", name="V-Three",
                       stake_amount=1000.0, uptime_percentage=92.0, is_active=False)
        session.add_all([v1, v2, v3])
        session.flush()

        tx1 = Transaction(tx_hash="0xseed_tx_1", bridge_id=bridge.id,
                          source_chain="QIE", destination_chain="Ethereum",
                          value=100.0, sender="qie1valone", receiver="0xrcpt1",
                          timestamp=datetime(2026, 9, 28, 12, 0, 0),
                          status=TransactionStatus.CONFIRMED,
                          anomaly_score=10.0, is_flagged=False)
        tx2 = Transaction(tx_hash="0xseed_tx_2", bridge_id=bridge.id,
                          source_chain="QIE", destination_chain="Ethereum",
                          value=999999.0, sender="qie1valone", receiver="0xrcpt2",
                          timestamp=datetime(2026, 9, 28, 12, 5, 0),
                          status=TransactionStatus.FAILED,
                          anomaly_score=70.0, is_flagged=True)
        session.add_all([tx1, tx2])
        session.flush()

        # detected_at / created_at default to "now" (which is NOT the seeded
        # day) — pin them to the seeded date so the daily window matches.
        session.add(AnomalyDetection(
            transaction_id=tx2.id, anomaly_score=70.0, confidence=90.0,
            model_version="test", severity=SeverityLevel.HIGH,
            detected_at=datetime(2026, 9, 28, 12, 5, 0)))
        session.add(Alert(
            transaction_id=tx2.id, alert_type=AlertType.ANOMALY,
            severity=SeverityLevel.HIGH, message="seed alert",
            created_at=datetime(2026, 9, 28, 12, 5, 0)))


class TestAuthGuard:
    def test_both_endpoints_require_token(self, client):
        for path in ("/api/v1/analytics/model-accuracy",
                     "/api/v1/analytics/validator-stats"):
            r = client.get(path)
            assert r.status_code == 401
            assert r.get_json()["code"] == "AUTH_REQUIRED"


class TestModelAccuracy:
    def test_returns_real_metrics_file_values(self, client, token):
        r = client.get("/api/v1/analytics/model-accuracy", headers=_auth(token))
        assert r.status_code == 200
        data = r.get_json()["data"]
        # The trained artifact's metrics — must be real numbers from
        # metrics_latest.json, not fabricated.
        for key in ("accuracy", "precision", "recall", "f1_score"):
            assert key in data
            assert data[key] is not None, f"{key} missing from metrics file"
            assert isinstance(data[key], (int, float))
        assert data.get("model_version")

    def test_missing_file_is_honest_empty_state(self):
        data = flask_app_module._load_model_metrics(
            metrics_path=str(_ROOT / "backend" / "ml" / "models" / "nope.json")
        )
        assert data["accuracy"] is None
        assert data["f1_score"] is None
        assert "error" in data
        assert "unavailable" in data["error"]


class TestValidatorStatsSeeded:
    @pytest.fixture(autouse=True)
    def seed(self):
        _truncate_all_tables()
        _seed_known_data()
        yield
        _truncate_all_tables()

    def test_real_db_aggregates(self, client, token):
        r = client.get("/api/v1/analytics/validator-stats", headers=_auth(token))
        assert r.status_code == 200
        data = r.get_json()["data"]

        assert data["total_validators"] == 3
        assert data["active_validators"] == 2
        assert data["avg_uptime"] == 96.0          # (99 + 97 + 92) / 3
        assert data["total_staked"] == "6000 aqie"  # 4000 + 1000 + 1000
        assert data["transactions_total"] == 2
        assert data["alerts_total"] == 1
        assert data["alerts_unresolved"] == 1

    def test_top_validator_counts_and_voting_power(self, client, token):
        r = client.get("/api/v1/analytics/validator-stats", headers=_auth(token))
        data = r.get_json()["data"]

        assert len(data["top_validators"]) == 3
        top = data["top_validators"][0]
        assert top["address"] == "qie1valone"        # highest stake first
        assert top["voting_power"] == 66.67          # 4000 / 6000 * 100
        assert top["transactions"] == 2               # sender == validator addr
        assert top["alerts"] == 1                     # alert on tx2
        # Validators with no originating transactions report honest zeros.
        assert data["top_validators"][1]["transactions"] == 0
        assert data["top_validators"][1]["alerts"] == 0

    def test_voting_power_uses_rpc_and_marks_source(self, client, token, monkeypatch):
        monkeypatch.setattr(
            flask_app_module.qie_manager,
            "get_validator_set",
            lambda: {
                "success": True,
                "validators": [
                    {"address": "qie1valone", "voting_power": "60"},
                    {"address": "qie1valtwo", "voting_power": "30"},
                    {"address": "qie1valthree", "voting_power": "10"},
                ],
            },
        )

        r = client.get("/api/v1/analytics/validator-stats", headers=_auth(token))
        data = r.get_json()["data"]

        assert r.status_code == 200
        assert data["top_validators"][0]["voting_power"] == 60.0
        assert data["top_validators"][0]["source"] == "rpc"

    def test_voting_power_falls_back_to_db_and_marks_source(self, client, token, monkeypatch):
        monkeypatch.setattr(
            flask_app_module.qie_manager,
            "get_validator_set",
            lambda: {"success": False, "validators": []},
        )

        r = client.get("/api/v1/analytics/validator-stats", headers=_auth(token))
        data = r.get_json()["data"]

        assert r.status_code == 200
        assert data["top_validators"][0]["voting_power"] == 66.67
        assert data["top_validators"][0]["source"] == "db"

    def test_node_telemetry_degrades_gracefully(self, client, token):
        r = client.get("/api/v1/analytics/validator-stats", headers=_auth(token))
        data = r.get_json()["data"]
        # No QIE node in the test environment: telemetry must say unavailable
        # with neutral values — and the endpoint still returns DB data.
        assert data["node"]["available"] is False
        assert data["node"]["block_height"] == 0
        assert data["node"]["synced"] is False


class TestValidatorStatsEmpty:
    @pytest.fixture(autouse=True)
    def empty(self):
        _truncate_all_tables()
        yield
        _truncate_all_tables()

    def test_honest_empty_state(self, client, token):
        r = client.get("/api/v1/analytics/validator-stats", headers=_auth(token))
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert data["total_validators"] == 0
        assert data["active_validators"] == 0
        assert data["top_validators"] == []
        assert data["transactions_total"] == 0
        assert data["alerts_total"] == 0
        # Node stays unreachable but the endpoint still succeeds.
        assert data["node"]["available"] is False

    def test_daily_stats_empty_day_is_not_100_percent(self, client, token):
        r = client.get("/api/v1/analytics/daily-stats?date=2020-01-01",
                       headers=_auth(token))
        assert r.status_code == 200
        data = r.get_json()["data"]
        # Honest empty state: no txs that day -> None, never a fabricated 100.0
        assert data["total_transactions"] == 0
        assert data["validation_success_rate"] is None
        assert data["avg_anomaly_score"] == 0.0


class TestDailyStatsSeeded:
    @pytest.fixture(autouse=True)
    def seed(self):
        _truncate_all_tables()
        _seed_known_data()
        yield
        _truncate_all_tables()

    def test_real_daily_aggregates(self, client, token):
        r = client.get("/api/v1/analytics/daily-stats?date=2026-09-28",
                       headers=_auth(token))
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert data["total_transactions"] == 2
        assert data["anomalies_detected"] == 1
        # 1 of 2 flagged -> 50% success rate (real computation)
        assert data["validation_success_rate"] == 50.0
        assert data["avg_anomaly_score"] == 70.0
        assert data["high_alerts"] == 1
