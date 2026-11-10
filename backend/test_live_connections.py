"""Protocol routing regressions for HTTPS mainnet Tendermint connections."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ingestion.worker import IngestionWorker
from qie_node_manager import QIENodeManager


@pytest.mark.parametrize("url,expected", [
    ("https://rpc.cosmos.directory/qie", True),
    ("https://rpc.qie.digital", True),
    ("https://tendermint.qie.digital", True),
    ("http://localhost:26657", True),
    ("https://rpc1mainnet.qie.digital", False),
    ("https://rpc1testnet.qie.digital", False),
])
def test_auto_protocol_supports_https_tendermint(monkeypatch, url, expected):
    monkeypatch.setenv("QIE_RPC_PROTOCOL", "auto")
    assert QIENodeManager(rpc_url=url).uses_tendermint_rpc() is expected


def test_https_tendermint_worker_polls_mempool_and_blocks(monkeypatch):
    monkeypatch.setenv("QIE_RPC_PROTOCOL", "tendermint")
    monkeypatch.setenv("MEMPOOL_ENABLED", "1")
    monkeypatch.setenv("QIE_EVM_RPC_ENABLED", "0")
    manager = QIENodeManager(rpc_url="https://rpc.cosmos.directory/qie",
                             evm_rpc_url="http://localhost:8545")
    manager.rpc_call = Mock(side_effect=[
        {"txs": []}, {"block": {"header": {}, "data": {"txs": []}}},
    ])
    worker = IngestionWorker(node_manager=manager, db_manager=SimpleNamespace(),
                             anomaly_model=SimpleNamespace())
    assert worker.poll_once() == []
    assert [call.args[0] for call in manager.rpc_call.call_args_list] == [
        "unconfirmed_txs", "block",
    ]


def test_explicit_evm_protocol_skips_tendermint(monkeypatch):
    monkeypatch.setenv("QIE_RPC_PROTOCOL", "evm")
    assert not QIENodeManager(rpc_url="https://custom.example/rpc").uses_tendermint_rpc()
