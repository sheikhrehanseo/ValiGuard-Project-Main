"""
Shared pytest fixtures for the ValiGuard backend test suite.
"""

import sys
import os
from pathlib import Path

import pytest

# Never start the background ingestion worker from a test process, and isolate
# unit tests from live internet RPC URLs configured in .env.
os.environ.setdefault("VALIGUARD_INGESTION_WORKER", "0")
os.environ["QIE_RPC_URL"] = "http://localhost:26657"
os.environ["QIE_EVM_RPC_URL"] = "http://localhost:8545"

sys.path.insert(0, str(Path(__file__).parent))

collect_ignore = ["test_qie_node_manager.py"]


@pytest.fixture
def manager():
    """QIENodeManager instance for RPC tests."""
    from qie_node_manager import QIENodeManager
    return QIENodeManager()