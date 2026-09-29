"""
Shared pytest fixtures for the ValiGuard backend test suite.
"""

import sys
import os
from pathlib import Path

import pytest

# Never start the background ingestion worker from a test process.
os.environ.setdefault("VALIGUARD_INGESTION_WORKER", "0")

sys.path.insert(0, str(Path(__file__).parent))

# test_qie_node_manager.py is a manual smoke script that calls a LIVE QIE
# RPC node (no assertions; see its docstring). Exclude it from pytest runs.
collect_ignore = ["test_qie_node_manager.py"]


@pytest.fixture
def manager():
    """QIENodeManager instance for RPC tests (no live node required —
    the manager's methods degrade gracefully when the node is offline)."""
    from qie_node_manager import QIENodeManager
    return QIENodeManager()
