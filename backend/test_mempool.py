"""Stage 4 honest raw-entry mempool tests."""

import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from database.db import DatabaseConfig, DatabaseManager
from database.models import Alert, AnomalyDetection, Transaction, TransactionStatus
from ingestion.worker import IngestionWorker
from test_alert_thresholds import FixedScoreModel


class FakeRpcNode:
    def __init__(self, mempool_pages, block_pages):
        self.rpc_url = "http://qie.test:26657"
        self._mempool_pages = iter(mempool_pages)
        self._block_pages = iter(block_pages)


class RawScoreModel(FixedScoreModel):
    def score(self, transaction):
        result = super().score(transaction)
        result["reason"] = "temporal burst"
        return result


class UnavailableModel:
    feature_extractor = None

    def score(self, transaction):
        return {
            "risk_score": None,
            "confidence": 0,
            "severity": "low",
            "reason": "model_unavailable",
            "model_version": "fallback",
            "features": [],
            "model_unavailable": True,
        }


def _worker(tmp_path, model=None):
    database = DatabaseManager(
        DatabaseConfig(f"sqlite:///{tmp_path / 'mempool.db'}")
    )
    database.init_db()
    node = FakeRpcNode([], [])
    worker = IngestionWorker(
        node_manager=node,
        db_manager=database,
        anomaly_model=model or RawScoreModel(),
    )
    return worker, database


def _patch_rpc(worker, mempool_pages, block_pages):
    mempool = iter(mempool_pages)
    blocks = iter(block_pages)

    def fast_rpc(method):
        if method == "unconfirmed_txs":
            return next(mempool)
        return next(blocks)

    worker._fast_rpc_call = fast_rpc


def _block(entry):
    return {
        "block": {
            "header": {"height": "12", "time": "2026-09-30T00:00:00Z"},
            "data": {"txs": [entry]},
        }
    }


def test_raw_entry_hash_nulls_pending_and_confirmation(tmp_path):
    raw_bytes = b"raw-qie-transaction"
    encoded = base64.b64encode(raw_bytes).decode()
    expected_hash = hashlib.sha256(raw_bytes).hexdigest()
    worker, database = _worker(tmp_path)
    _patch_rpc(
        worker,
        [{"txs": [encoded]}, {"txs": []}],
        [{"block": {"header": {}, "data": {"txs": []}}}, _block(encoded)],
    )

    first = worker.poll_once()
    assert len(first) == 1
    with database.get_session() as session:
        transaction = session.query(Transaction).one()
        assert transaction.tx_hash == expected_hash
        assert transaction.sender is None
        assert transaction.receiver is None
        assert transaction.value is None
        assert transaction.source_chain is None
        assert transaction.destination_chain is None
        assert transaction.status == TransactionStatus.PENDING
        detection = session.query(AnomalyDetection).one()
        assert "raw entry (volume unavailable)" in detection.reason
        assert detection.features_used["volume_available"] is False

    confirmed = worker.poll_once()
    assert len(confirmed) == 1
    assert confirmed[0]["status"] == "confirmed"
    assert worker.poll_once() == []
    with database.get_session() as session:
        assert session.query(Transaction).count() == 1
        assert session.query(Transaction).one().status == TransactionStatus.CONFIRMED
        assert session.query(AnomalyDetection).count() == 2


def test_empty_mempool_creates_zero_records(tmp_path):
    worker, database = _worker(tmp_path)
    _patch_rpc(
        worker,
        [{"txs": []}],
        [{"block": {"header": {}, "data": {"txs": []}}}],
    )

    assert worker.poll_once() == []
    with database.get_session() as session:
        assert session.query(Transaction).count() == 0


def test_model_unavailable_persists_no_score_or_detection(tmp_path):
    encoded = base64.b64encode(b"model-unavailable").decode()
    worker, database = _worker(tmp_path, model=UnavailableModel())
    _patch_rpc(
        worker,
        [{"txs": [encoded]}],
        [{"block": {"header": {}, "data": {"txs": []}}}],
    )

    assert len(worker.poll_once()) == 1
    with database.get_session() as session:
        transaction = session.query(Transaction).one()
        assert transaction.anomaly_score is None
        assert session.query(AnomalyDetection).count() == 0
        assert session.query(Alert).count() == 0


def test_rpc_down_creates_no_records_and_worker_can_continue(tmp_path):
    worker, database = _worker(tmp_path)

    def down(method):
        raise TimeoutError(f"{method} unavailable")

    worker._fast_rpc_call = down
    assert worker.poll_once() == []
    assert worker.poll_once() == []
    with database.get_session() as session:
        assert session.query(Transaction).count() == 0


def test_migration_upgrade_and_downgrade(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    root = Path(__file__).parent.parent
    backend = root / "backend"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["PYTHONPATH"] = str(root)

    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert upgrade.returncode == 0, upgrade.stderr

    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "downgrade", "a1f2c3d4e5b6"],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert downgrade.returncode == 0, downgrade.stderr
