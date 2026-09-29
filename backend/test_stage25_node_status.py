"""Stage 2.5 tests for fast telemetry and chain validator power."""

import time
from pathlib import Path
import sys

import requests

sys.path.insert(0, str(Path(__file__).parent))

from qie_node_manager import QIENodeManager


def test_node_probe_fails_fast_when_rpc_is_down(monkeypatch):
    import app as app_module

    calls = []

    def fail_fast(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise requests.Timeout("node unavailable")

    monkeypatch.setattr(app_module.requests, "post", fail_fast)
    started = time.perf_counter()
    result = app_module._probe_node_telemetry()
    elapsed = time.perf_counter() - started

    assert result["available"] is False
    assert elapsed < 3.0
    assert calls == [3]


def test_node_probe_cache_avoids_reprobe_inside_ttl(monkeypatch):
    import app as app_module

    calls = []

    def fake_probe():
        calls.append(True)
        return {"available": True, "block_height": len(calls)}

    monkeypatch.setattr(app_module, "_probe_node_telemetry", fake_probe)
    monkeypatch.setattr(
        app_module,
        "_node_telemetry_cache",
        {"data": None, "fetched_at": 0.0},
    )

    first = app_module._fetch_node_telemetry()
    second = app_module._fetch_node_telemetry()

    assert first == second
    assert len(calls) == 1

    app_module._node_telemetry_cache["fetched_at"] = (
        time.time() - app_module.NODE_TELEMETRY_TTL_SECONDS - 1
    )
    refreshed = app_module._fetch_node_telemetry()

    assert refreshed["block_height"] == 2
    assert len(calls) == 2


def test_node_status_endpoint_uses_fast_cached_probe(monkeypatch):
    import app as app_module

    telemetry = {
        "available": False,
        "online": False,
        "synced": False,
        "block_height": 0,
        "moniker": "",
    }
    monkeypatch.setattr(app_module, "_fetch_node_telemetry", lambda: telemetry)
    monkeypatch.setattr(
        app_module.qie_manager,
        "check_node_health",
        lambda: (_ for _ in ()).throw(AssertionError("slow health check used")),
    )
    monkeypatch.setattr(
        app_module.qie_manager,
        "get_node_status",
        lambda: (_ for _ in ()).throw(AssertionError("slow status check used")),
    )

    response = app_module.app.test_client().get("/api/v1/qie/node/status")

    assert response.status_code == 200
    assert response.get_json()["data"]["node"]["online"] is False


def test_validator_set_handles_pagination(monkeypatch):
    manager = QIENodeManager(rpc_url="http://qie.test:26657")
    pages = {
        1: {
            "result": {
                "block_height": "100",
                "total": "3",
                "validators": [
                    {"address": "qie1one", "voting_power": "60"},
                    {"address": "qie1two", "voting_power": "30"},
                ],
            }
        },
        2: {
            "result": {
                "block_height": "100",
                "total": "3",
                "validators": [{"address": "qie1three", "voting_power": "10"}],
            }
        },
    }
    requested_pages = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, timeout):
        requested_pages.append((url, params, timeout))
        return Response(pages[params["page"]])

    monkeypatch.setattr("qie_node_manager.requests.get", fake_get)
    result = manager.get_validator_set(per_page=2)

    assert result["success"] is True
    assert result["total"] == 3
    assert [item["address"] for item in result["validators"]] == [
        "qie1one",
        "qie1two",
        "qie1three",
    ]
    assert [item[1]["page"] for item in requested_pages] == [1, 2]
    assert all(item[2] == 3 for item in requested_pages)
