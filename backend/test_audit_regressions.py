"""Behavioral regressions from the live-dashboard review."""

from datetime import datetime
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from auth.jwt_auth import create_token
from database import DatabaseConfig, DatabaseManager, Transaction, TransactionStatus
from ingestion.worker import IngestionWorker
from qie_node_manager import QIENodeManager
from test_alert_thresholds import FixedScoreModel
from test_mempool import UnavailableModel


@pytest.fixture
def context(tmp_path, monkeypatch):
    import app
    db = DatabaseManager(DatabaseConfig(f"sqlite:///{tmp_path / 'review.db'}"))
    db.init_db()
    monkeypatch.setattr(app, "db_manager", db)
    monkeypatch.setattr(app, "ingestion_worker", None)
    monkeypatch.setattr(app, "anomaly_model", FixedScoreModel())
    headers = {"Authorization": "Bearer " + create_token("0x" + "2" * 40)}
    return app, db, headers


def test_anonymous_writes_and_socket_are_rejected(context):
    app, db, _ = context
    for path in ("anomaly-score", "validate-cross-chain"):
        assert app.app.test_client().post("/api/v1/bridge/" + path, json={}).status_code == 401
    socket = app.socketio.test_client(app.app)
    assert not socket.is_connected()
    with db.get_session() as session:
        assert session.query(Transaction).count() == 0


def test_http_cannot_overwrite_existing_transaction(context):
    app, db, headers = context
    with db.get_session() as session:
        session.add(Transaction(tx_hash="stored", value=500000, anomaly_score=95,
                                is_flagged=True, status=TransactionStatus.CONFIRMED))
    response = app.app.test_client().post("/api/v1/bridge/anomaly-score",
        json={"transaction_hash": "stored", "amount": 1}, headers=headers)
    assert response.status_code == 409
    with db.get_session() as session:
        tx = session.query(Transaction).one()
        assert (tx.value, tx.anomaly_score, tx.is_flagged, tx.status) == (
            500000, 95, True, TransactionStatus.CONFIRMED)


def test_missing_model_does_not_validate_transaction(context, monkeypatch):
    app, db, headers = context
    monkeypatch.setattr(app, "anomaly_model", UnavailableModel())
    response = app.app.test_client().post("/api/v1/bridge/validate-cross-chain", headers=headers,
        json={"transaction_hash": "unscored", "amount": 100, "source_chain": "QIE", "dest_chain": "Ethereum"})
    assert response.status_code == 503
    assert response.get_json()["data"]["valid"] is None
    assert response.get_json()["data"]["model_available"] is False
    with db.get_session() as session:
        assert session.query(Transaction).one().status == TransactionStatus.PENDING


def test_pending_can_become_failed_without_duplicates(context):
    _, db, _ = context
    worker = IngestionWorker(node_manager=SimpleNamespace(), db_manager=db, anomaly_model=FixedScoreModel())
    tx = {"hash": "reverted", "sender": "sender", "value": 1}
    worker.process_raw_transaction({**tx, "status": "pending"})
    result = worker.process_raw_transaction({**tx, "status": "failed", "height": 1})
    assert result["status"] == "failed"
    assert worker.process_raw_transaction({**tx, "status": "pending"}) is None
    with db.get_session() as session:
        assert session.query(Transaction).one().status == TransactionStatus.FAILED


def test_backfill_retries_missing_block_and_advances_after_consumption(context):
    _, db, _ = context
    def block(height):
        return {"found": True, "height": height, "transactions": [{"hash": str(height)}]}
    node = SimpleNamespace(get_evm_latest_block=lambda **_: block(110),
                           get_evm_block_by_number=Mock(side_effect=lambda h, **_: block(h)))
    worker = IngestionWorker(node_manager=node, db_manager=db, anomaly_model=FixedScoreModel())
    worker._last_evm_block_height = 100
    stream = worker._fetch_evm_latest_block_txs()
    assert next(stream)["height"] == 101
    assert worker._last_evm_block_height == 100  # No checkpoint before caller commits.
    stream.close()
    node.get_evm_block_by_number.side_effect = lambda h, **_: {"found": False} if h == 103 else block(h)
    assert [tx["height"] for tx in worker._fetch_evm_latest_block_txs()] == [101, 102]
    assert worker._last_evm_block_height == 102
    node.get_evm_block_by_number.side_effect = lambda h, **_: block(h)
    assert [tx["height"] for tx in worker._fetch_evm_latest_block_txs()] == list(range(103, 111))


def test_populated_legacy_migration_converts_empty_addresses():
    versions = Path(__file__).parent / "database" / "versions"
    def load(filename):
        spec = importlib.util.spec_from_file_location("migration_test", versions / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    initial = load("20260928_73004a4a6ea8_initial_schema.py")
    nullable = load("20260930_b2c3d4e5f6a7_raw_entry_nullable.py")
    with create_engine("sqlite:///:memory:").begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            initial.upgrade()
            connection.execute(text("INSERT INTO bridges (id,address,chain_name,status,created_at) VALUES (1,'bridge','QIE','ACTIVE',CURRENT_TIMESTAMP)"))
            connection.execute(text("INSERT INTO transactions (tx_hash,bridge_id,source_chain,destination_chain,value,sender,receiver,timestamp,status,created_at) VALUES ('raw',1,'QIE','QIE',0,'','',CURRENT_TIMESTAMP,'PENDING',CURRENT_TIMESTAMP)"))
            nullable.upgrade()
            assert connection.execute(text("SELECT sender,receiver FROM transactions")).one() == (None, None)


def test_token_volume_is_excluded_from_native_total(context):
    app, db, headers = context
    with db.get_session() as session:
        session.add_all([
            Transaction(tx_hash="native", value=2, asset_symbol="QIE", source_chain="QIE"),
            Transaction(tx_hash="token", value=100, asset_symbol="USDC", asset_address="0xtoken", source_chain="USDC"),
        ])
    response = app.app.test_client().get("/api/v1/analytics/daily-stats", headers=headers)
    data = response.get_json()["data"]
    assert data["total_volume"] == 2
    assert data["total_transactions"] == 2
    token_route = next(route for route in data["bridge_routes"] if route["chain"] == "USDC")
    assert token_route["volume"] == 0
    assert token_route["asset_volumes"][0]["volume"] == 100


def test_evm_tls_failure_is_not_retried_without_verification(monkeypatch):
    post = Mock(side_effect=requests.exceptions.SSLError("untrusted certificate"))
    monkeypatch.setattr("qie_node_manager.requests.post", post)
    assert QIENodeManager().evm_rpc_call("eth_chainId") is None
    assert post.call_count == 1
    assert post.call_args.kwargs.get("verify", True) is True


def test_expired_socket_session_receives_no_telemetry(context):
    app, _, _ = context
    socket = app.socketio.test_client(app.app, auth={"token": create_token("0x" + "2" * 40)})
    assert socket.is_connected()
    for sid in app.socket_manager._sessions:
        app.socket_manager._sessions[sid] = 0
    app.socket_manager.emit_node_status({"height": 1})
    assert not socket.is_connected()


def test_relative_database_url_is_independent_of_working_directory(tmp_path, monkeypatch):
    original = DatabaseConfig("sqlite:///./valiguard.db").db_url
    monkeypatch.chdir(tmp_path)
    assert DatabaseConfig("sqlite:///./valiguard.db").db_url == original


def test_token_metadata_preserves_zero_decimals(monkeypatch):
    transfer = {
        "transaction_hash": "token-transfer",
        "from": {"hash": "sender"}, "to": {"hash": "receiver"},
        "token": {"symbol": "UNIT", "address_hash": "0xasset", "decimals": 0},
        "total": {"value": "123", "decimals": 0}, "block_number": 1,
    }
    def get(url, **kwargs):
        payload = {"items": [transfer]} if url.endswith("/token-transfers") else {"items": []}
        return SimpleNamespace(ok=True, json=lambda: payload)
    monkeypatch.setattr("qie_node_manager.requests.get", get)
    tx = QIENodeManager().get_explorer_recent_transactions()[0]
    assert (tx["value"], tx["asset_symbol"], tx["asset_address"]) == (123, "UNIT", "0xasset")


def test_block_receipt_failure_is_persisted_as_failed(context):
    _, db, _ = context
    node = SimpleNamespace(
        get_evm_latest_block=lambda **_: {"found": True, "height": 10, "transactions": [{"hash": "bad-tx"}]},
        get_evm_transaction_receipt=lambda *args, **kwargs: {"status": "0x0"},
    )
    worker = IngestionWorker(node_manager=node, db_manager=db, anomaly_model=FixedScoreModel())
    for tx in worker._fetch_evm_latest_block_txs():
        worker._handle_raw(tx)
    with db.get_session() as session:
        assert session.query(Transaction).one().status == TransactionStatus.FAILED


def test_assets_use_separate_ml_histories(tmp_path):
    import numpy as np
    from ml.anomaly_model import AnomalyModel
    model = AnomalyModel(str(tmp_path))
    model.model = SimpleNamespace(predict=lambda _: np.array([1]), decision_function=lambda _: np.array([0.2]))
    for symbol, address, value in [("QIE", None, 2), ("USDC", "0xasset", 1000000)]:
        model.score(SimpleNamespace(sender="sender", timestamp=datetime.utcnow(), value=value,
                                    asset_symbol=symbol, asset_address=address))
    assert list(model._asset_extractors["native:QIE"]._value_history) == [2]
    assert list(model._asset_extractors["0xasset"]._value_history) == [1000000]
