"""Stage 5 simulator and launcher tests.

Covers:
  * Scenario payload generators: valid API payloads with the intended
    characteristics (sweep far above baseline, burst sender concentration,
    replay identical amounts, fresh unique hashes).
  * submit() targets the OPEN /api/v1/bridge/anomaly-score endpoint.
  * --verify aggregation logic returns per-scenario tiers and exit codes.
  * End-to-end smoke: the simulator's HTTP client against a real test app
    instance -> full Flask -> core/scoring -> DB path; asserts >= 1 Alert
    row and detection monotonicity (sweep risk >= normal risk).
  * Launcher argument/mode handling (full boot is a human acceptance step).
"""

import importlib.util
import os
import random
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

# --- isolated test DB BEFORE importing the app (it binds at import) --------
# In a full-suite run the app is already bound to another temp test DB
# (test_analytics.py is collected first); this assignment is then inert.
_TEST_DB = os.path.join(tempfile.gettempdir(), "valiguard_test_simulator.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("VALIGUARD_INGESTION_WORKER", "0")


def load_simulator():
    spec = importlib.util.spec_from_file_location(
        "traffic_simulator", ROOT / "scripts" / "generate_mock_traffic.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_launcher():
    spec = importlib.util.spec_from_file_location("project_launcher", ROOT / "start_project.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- payload generator tests -----------------------------------------------

def test_scenario_payload_characteristics():
    simulator = load_simulator()
    rng = random.Random(7)

    normal = simulator.normal_payload(rng)
    sweep = simulator.large_sweep_payload(rng)
    burst = simulator.burst_payloads(rng)
    replay = simulator.replay_payloads(rng)

    # Normal: ordinary amounts, well below the attack scenarios.
    assert 1.0 <= normal["amount"] <= simulator.NORMAL_AMOUNT_CAP
    # Sweep: far outside the trained baseline.
    assert sweep["amount"] >= simulator.SWEEP_VALUE_RANGE[0]
    # Burst: rapid-fire from ONE sender.
    assert len(burst) == simulator.BURST_EPISODE_TXS
    assert len({p["sender"] for p in burst}) == 1
    assert all(simulator.BURST_AMOUNT_RANGE[0] <= p["amount"]
              <= simulator.BURST_AMOUNT_RANGE[1] for p in burst)
    # Replay: same sender AND same amount, fresh unique hashes.
    assert len(replay) == simulator.REPLAY_EPISODE_TXS
    assert len({p["sender"] for p in replay}) == 1
    assert len({p["amount"] for p in replay}) == 1
    assert len({p["transaction_hash"] for p in replay}) == len(replay)

    for payload in (normal, sweep, *burst, *replay):
        assert payload["transaction_hash"].startswith("0x")
        assert payload["source_chain"]
        assert payload["dest_chain"]
        assert payload["receiver"]


def test_payloads_are_reproducible_with_seed():
    simulator = load_simulator()
    payloads_a = [simulator.normal_payload(random.Random(99)) for _ in range(2)]
    # Same seed + fresh RNG -> the simulator's --seed flag reproduces runs.
    rng = random.Random(99)
    assert simulator.normal_payload(rng)["amount"] == payloads_a[0]["amount"]


# --- submit() target endpoint ----------------------------------------------

def test_simulator_submit_uses_open_anomaly_endpoint(monkeypatch):
    simulator = load_simulator()
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"data": {"severity": "medium", "anomaly_score": 45}}

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(simulator.requests, "post", fake_post)
    payload = simulator.normal_payload(random.Random(1))
    result = simulator.submit("http://localhost:5000", payload)

    assert captured["url"].endswith("/api/v1/bridge/anomaly-score")
    assert captured["json"] == payload
    assert result.severity == "medium"
    assert result.status_code == 200


# --- --verify aggregation ----------------------------------------------------

def _tier_by_amount(amount):
    """Map a payload amount to the tier the fake backend should return."""
    if amount >= 500_000:
        return "critical"
    if amount >= 2_200:
        return "high"
    if amount >= 700:
        return "medium"
    return "low"


def test_verify_reports_per_scenario_tiers(monkeypatch, capsys):
    simulator = load_simulator()

    def fake_submit(api_url, payload, timeout=10.0):
        tier = _tier_by_amount(payload["amount"])
        return simulator.ScenarioResult("", tier, 200,
                                        {"anomaly_score": 50})

    monkeypatch.setattr(simulator, "submit", fake_submit)
    # fake_submit ignores the sleep pacing monkeypatched below to keep fast.
    monkeypatch.setattr(simulator.time, "sleep", lambda *_: None)
    assert simulator.verify("http://test", simulator.SCENARIOS, seed=3) == 0
    output = capsys.readouterr().out
    for scenario in simulator.SCENARIOS:
        assert scenario in output
    assert "PASS" in output


def test_verify_exits_nonzero_on_target_miss(monkeypatch, capsys):
    simulator = load_simulator()

    def fake_submit(api_url, payload, timeout=10.0):
        # Everything scores low -> every non-normal scenario misses.
        return simulator.ScenarioResult("", "low", 200, {"anomaly_score": 10})

    monkeypatch.setattr(simulator, "submit", fake_submit)
    monkeypatch.setattr(simulator.time, "sleep", lambda *_: None)
    assert simulator.verify("http://test", simulator.SCENARIOS, seed=3) == 1
    assert "MISS" in capsys.readouterr().out


# --- end-to-end smoke against a real app instance ---------------------------

def test_smoke_full_pipeline_produces_alerts_and_detections():
    """
    Boot the real Flask app on an ephemeral port and drive it with the
    simulator's HTTP client: normal + sweep + burst mix must produce
    AnomalyDetection rows, at least one Alert row (medium+ fires alerts),
    and sweep must score at least as risky as a normal tx (value signal
    is monotone). Exact tiers are hour-dependent with the current model
    (see the Stage 5 report), so tier equality is NOT asserted here.
    """
    # Guard: only run against a throwaway test DB, never the dev database.
    import app as flask_app_module  # noqa: E402 — singleton, already bound
    bound_url = flask_app_module.db_manager.config.db_url.replace("\\", "/")
    assert "valiguard_test" in bound_url, (
        f"refusing to smoke-test against non-test DB: {bound_url}"
    )

    from database.models import (  # noqa: E402
        Alert, AnomalyDetection, Bridge, Transaction, Validator,
    )

    def truncate():
        with flask_app_module.db_manager.get_session() as session:
            for model in (Alert, AnomalyDetection, Transaction, Validator, Bridge):
                session.query(model).delete()

    truncate()
    try:
        from werkzeug.serving import make_server

        server = make_server("127.0.0.1", 0, flask_app_module.app)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            simulator = load_simulator()
            base = f"http://127.0.0.1:{port}"
            rng = random.Random(11)

            submitted = (
                [simulator.normal_payload(rng) for _ in range(6)]
                + [simulator.large_sweep_payload(rng)]
                + simulator.burst_payloads(rng, count=4)
            )
            for payload in submitted:
                result = simulator.submit(base, payload)
                assert result.status_code == 200, (
                    f"simulator submission failed: {result.status_code} "
                    f"{result.data}"
                )

            with flask_app_module.db_manager.get_session() as session:
                detections = session.query(AnomalyDetection).all()
                alerts = session.query(Alert).all()
                assert len(detections) == len(submitted)
                assert len(alerts) >= 1, (
                    "expected at least one Alert row (medium+ fires alerts)"
                )

                by_hash = {
                    d.transaction.tx_hash: d for d in detections
                }
                normal_scores = [
                    by_hash[p["transaction_hash"]].anomaly_score
                    for p in submitted[:6]
                ]
                sweep_score = by_hash[
                    submitted[6]["transaction_hash"]
                ].anomaly_score
                assert sweep_score >= max(normal_scores), (
                    "sweep should score at least as risky as normal txs"
                )
        finally:
            server.shutdown()
            thread.join(timeout=5)
    finally:
        truncate()


# --- launcher argument/mode handling ---------------------------------------

def test_launcher_demo_and_default_modes():
    launcher = load_launcher()
    base = {"MEMPOOL_ENABLED": "0"}

    demo = launcher.configure_environment(True, base)
    assert demo["VALIGUARD_INGESTION_WORKER"] == "0"
    assert demo["NEXT_PUBLIC_DEMO_MODE"] == "true"

    default = launcher.configure_environment(False, base)
    assert default["VALIGUARD_INGESTION_WORKER"] == "1"
    assert default["MEMPOOL_ENABLED"] == "0"
    assert default["NEXT_PUBLIC_DEMO_MODE"] == "false"


def test_launcher_parser_supports_demo_simulation():
    launcher = load_launcher()
    args = launcher.build_parser().parse_args(["--demo", "--simulate", "--no-browser"])
    assert args.demo is True
    assert args.simulate is True
    assert args.no_browser is True


def test_launcher_port_conflict_error_names_pid(monkeypatch):
    launcher = load_launcher()
    monkeypatch.setattr(launcher, "port_in_use", lambda port: True)
    monkeypatch.setattr(launcher, "find_port_pid", lambda port: "4242")
    try:
        launcher.check_ports_free()
    except RuntimeError as exc:
        assert "5000" in str(exc)
        assert "4242" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on busy port")
