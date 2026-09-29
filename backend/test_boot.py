"""Regression test for default Flask application startup."""

import os
import subprocess
import sys
from pathlib import Path


def test_default_import_starts_without_worker_override():
    """The worker-enabled import path must not raise during module loading."""
    root = Path(__file__).parent.parent
    environment = os.environ.copy()
    environment.pop("VALIGUARD_INGESTION_WORKER", None)
    environment["PYTHONPATH"] = str(root)

    result = subprocess.run(
        [sys.executable, "-c", "import backend.app"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
