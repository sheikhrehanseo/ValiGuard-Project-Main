#!/usr/bin/env python
"""
ValiGuard AI traffic simulator — HTTP-only demo traffic.

Every request goes through Flask's open /api/v1/bridge/anomaly-score
endpoint, then through the shared scorer (core/scoring.py), database, and
Socket.IO event path. No backend modules are imported and no database
writes are performed here — the point is to exercise the full stack.

Scenarios (target tier in parentheses):
    normal       small varied values, many senders            (low)
    large-sweep  value far outside the trained baseline        (critical)
    burst        rapid-fire episode from ONE sender             (high)
    replay       same sender, same amount, fresh hashes         (medium/high)

Documented limitations:
  * Timestamps are server-side, so off-hours/temporal anomalies cannot be
    simulated in real time; the model's odd-hours feature tracks the
    server clock, not this script.
  * The live frequency feature (ml/feature_extraction.py) computes
    sender_rate/baseline_rate - 1 against its own rolling history, which is
    <= 0 for any sender; burst/replay therefore cannot rely on the
    frequency feature and are calibrated through their value multipliers.
    Sender/amount concentration is kept as demo narrative.
  * The value normalizer uses a rolling p95 of recent values, so the mix
    must stay ~85%+ normal traffic or the percentile adapts to the attack
    values and the tiers collapse. MIX_WEIGHTS is calibrated for that.

Calibration: run with --verify to submit one episode per scenario, print
the tier each actually produced, and exit nonzero if any scenario misses
its target. Tune the value constants in this file (never the backend
thresholds — those are the Stage 2 contract).

Examples:
    python scripts/generate_mock_traffic.py
    python scripts/generate_mock_traffic.py --verify
    python scripts/generate_mock_traffic.py --rate 1.0 --duration 120 --seed 7
"""

from __future__ import annotations

import argparse
import random
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import requests

DEFAULT_API_URL = "http://localhost:5000"
ENDPOINT_PATH = "/api/v1/bridge/anomaly-score"

SCENARIOS = ("normal", "large-sweep", "burst", "replay")
TARGET_TIERS: Dict[str, Tuple[str, ...]] = {
    "normal": ("low",),
    "large-sweep": ("critical",),
    "burst": ("high",),
    "replay": ("medium", "high"),
}

# Normal-heavy mix keeps the rolling p95 normalizer inside the normal range
# (see module docstring). Sweep+burst+replay stay under ~5% each.
MIX_WEIGHTS: Dict[str, float] = {
    "normal": 0.86,
    "large-sweep": 0.04,
    "burst": 0.06,
    "replay": 0.04,
}

# Value calibration against the trained model (empirical, via --verify):
#   * Training normals have value_normalized p50 ~= 0.08, p95 ~= 0.97, so
#     normal traffic uses a log-normal amount distribution with the same
#     sigma (1.5), which reproduces that p50/p95 ratio live.
#   * The model's decision range is narrow (max risk ~= 62): value_normalized
#     at the 2.0 cap is the ONLY reliably 'high' region, ~0.8-1.1 lands
#     'medium', and small normalized values stay 'low'. 'critical' (>= 80)
#     is unreachable with the current trained artifact — see the Stage 5
#     report; TARGET_TIERS keeps the spec targets so --verify reports the
#     miss honestly instead of silently lowering the bar.
NORMAL_AMOUNT_LOGMEAN = 4.0     # log-normal(mu=4, sigma=1.5), clamped below
NORMAL_AMOUNT_SIGMA = 1.5
NORMAL_AMOUNT_CAP = 3000.0
REPLAY_AMOUNT_RANGE = (700.0, 1100.0)    # ~0.8-1.1x the live p95 -> medium
BURST_AMOUNT_RANGE = (2200.0, 3500.0)    # ~2.4-3.9x p95 -> the 2.0 cap -> high
SWEEP_VALUE_RANGE = (500_000.0, 5_000_000.0)

BURST_EPISODE_TXS = 8
REPLAY_EPISODE_TXS = 4
EPISODE_INNER_DELAY = 0.2  # seconds between txs inside an episode

# The ingestion route is rate-limited at 100 req/min per IP (@rate_limit in
# backend/app.py). Stay safely under it regardless of --rate.
RATE_GOVERNOR_MAX_PER_MIN = 90

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

SOURCE_CHAINS = ("Ethereum", "BSC", "Polygon")
DESTINATION_CHAIN = "QIE"


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def random_hash(rng: random.Random) -> str:
    """Fresh tx hash per submission (uuid-based, unique per run)."""
    return "0x" + uuid.uuid4().hex


def _address(rng: random.Random, prefix: str) -> str:
    return f"{prefix}{''.join(rng.choice('0123456789abcdef') for _ in range(8))}"


@dataclass
class ScenarioResult:
    scenario: str
    severity: Optional[str]
    status_code: int
    data: Dict


# --- payload builders (pure, unit-testable) ---------------------------------

def normal_payload(rng: random.Random) -> Dict:
    """Ordinary bridge transfer: log-normal value, rotating sender."""
    amount = min(max(rng.lognormvariate(NORMAL_AMOUNT_LOGMEAN,
                                        NORMAL_AMOUNT_SIGMA), 1.0),
                 NORMAL_AMOUNT_CAP)
    return {
        "transaction_hash": random_hash(rng),
        "source_chain": rng.choice(SOURCE_CHAINS),
        "dest_chain": DESTINATION_CHAIN,
        "amount": round(amount, 2),
        "sender": _address(rng, "0xsim"),
        "receiver": _address(rng, "0xrcv"),
    }


def large_sweep_payload(rng: random.Random) -> Dict:
    """Value far outside the trained baseline (hits the 2.0 feature cap)."""
    return {
        "transaction_hash": random_hash(rng),
        "source_chain": rng.choice(SOURCE_CHAINS),
        "dest_chain": DESTINATION_CHAIN,
        "amount": round(rng.uniform(*SWEEP_VALUE_RANGE), 2),
        "sender": _address(rng, "0xsim"),
        "receiver": _address(rng, "0xrcv"),
    }


def burst_payloads(rng: random.Random,
                   count: int = BURST_EPISODE_TXS) -> List[Dict]:
    """One episode: rapid-fire txs from a SINGLE sender, elevated values."""
    sender = _address(rng, "0xsim")
    receiver = _address(rng, "0xrcv")
    chain = rng.choice(SOURCE_CHAINS)
    return [
        {
            "transaction_hash": random_hash(rng),
            "source_chain": chain,
            "dest_chain": DESTINATION_CHAIN,
            "amount": round(rng.uniform(*BURST_AMOUNT_RANGE), 2),
            "sender": sender,
            "receiver": receiver,
        }
        for _ in range(count)
    ]


def replay_payloads(rng: random.Random,
                    count: int = REPLAY_EPISODE_TXS) -> List[Dict]:
    """One episode: same sender, SAME amount, rapid repeats, fresh hashes."""
    sender = _address(rng, "0xsim")
    receiver = _address(rng, "0xrcv")
    chain = rng.choice(SOURCE_CHAINS)
    amount = round(rng.uniform(*REPLAY_AMOUNT_RANGE), 2)
    return [
        {
            "transaction_hash": random_hash(rng),
            "source_chain": chain,
            "dest_chain": DESTINATION_CHAIN,
            "amount": amount,
            "sender": sender,
            "receiver": receiver,
        }
        for _ in range(count)
    ]


def build_payloads(scenario: str, rng: random.Random) -> List[Dict]:
    """Payload list for one scenario episode (normal/sweep = single tx)."""
    if scenario == "normal":
        return [normal_payload(rng)]
    if scenario == "large-sweep":
        return [large_sweep_payload(rng)]
    if scenario == "burst":
        return burst_payloads(rng)
    if scenario == "replay":
        return replay_payloads(rng)
    raise ValueError(f"unknown scenario: {scenario}")


# --- HTTP client --------------------------------------------------------------

def submit(api_url: str, payload: Dict,
           timeout: float = 10.0) -> ScenarioResult:
    """
    POST one payload to the ingestion route.

    Network errors surface as status_code 0 (never raise).
    """
    try:
        response = requests.post(
            f"{api_url.rstrip('/')}{ENDPOINT_PATH}",
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException:
        return ScenarioResult(scenario="", severity=None, status_code=0,
                               data={})
    try:
        body = response.json()
    except ValueError:
        body = {}
    data = body.get("data", {}) if isinstance(body, dict) else {}
    return ScenarioResult(
        scenario="",
        severity=data.get("severity") if isinstance(data, dict) else None,
        status_code=response.status_code,
        data=data if isinstance(data, dict) else {},
    )


class RateGovernor:
    """Blocks sends once RATE_GOVERNOR_MAX_PER_MIN went out in the last 60s."""

    def __init__(self, max_per_min: int = RATE_GOVERNOR_MAX_PER_MIN):
        self.max_per_min = max_per_min
        self._send_times: deque = deque()

    def wait_for_slot(self) -> None:
        while True:
            now = time.time()
            while self._send_times and now - self._send_times[0] > 60.0:
                self._send_times.popleft()
            if len(self._send_times) < self.max_per_min:
                self._send_times.append(now)
                return
            time.sleep(max(0.1, 61.0 - (now - self._send_times[0])))


# --- run modes -----------------------------------------------------------------

def verify(api_url: str, scenarios: Iterable[str], seed: int = 42) -> int:
    """
    Calibration mode: one episode per scenario against the live backend,
    printing the tiers actually produced. Exits nonzero on any target miss.

    Sequence mirrors demo conditions: a normal warmup (builds the rolling
    value history), then each scenario episode followed by dilution normals
    so the p95 behaves as it does in the weighted demo loop.
    """
    rng = random.Random(seed)
    scenarios = list(scenarios)
    produced: Dict[str, List[str]] = {}

    def send(payload: Dict) -> Optional[str]:
        result = submit(api_url, payload)
        if result.status_code != 200:
            print(f"[{_now()}] HTTP {result.status_code} — "
                  "backend unreachable or error")
            return None
        print(f"[{_now()}] {payload['amount']:>14,.2f}  "
              f"score={result.data.get('anomaly_score')} "
              f"tier={result.severity}")
        return result.severity

    print("== VERIFY: warming up with 40 normal transactions ==")
    for _ in range(40):
        send(normal_payload(rng))
        time.sleep(0.15)

    for scenario in scenarios:
        print(f"\n== VERIFY scenario: {scenario} "
              f"(target: {'/'.join(TARGET_TIERS[scenario])}) ==")
        tiers = [send(p) for p in build_payloads(scenario, rng)]
        produced[scenario] = [t for t in tiers if t]
        time.sleep(EPISODE_INNER_DELAY)
        # Dilute the value history back toward normal before the next one.
        for _ in range(5):
            send(normal_payload(rng))
            time.sleep(0.15)

    print("\n== VERIFY summary ==")
    all_ok = True
    for scenario in scenarios:
        tiers = produced.get(scenario, [])
        best_rank = max((SEVERITY_RANK.get(t, -1) for t in tiers), default=-1)
        best = next(
            (t for t in tiers if SEVERITY_RANK.get(t, -1) == best_rank), None)
        passed = best in TARGET_TIERS[scenario]
        all_ok = all_ok and passed
        print(f"  {scenario:<12} produced={tiers} best={best} "
              f"target={'/'.join(TARGET_TIERS[scenario])} "
              f"{'PASS' if passed else 'MISS'}")
    print("\nVERIFY result:",
          "ALL SCENARIOS ON TARGET" if all_ok
          else "OFF TARGET — tune simulator value constants")
    return 0 if all_ok else 1


def run(api_url: str, rate: float, duration: float, scenarios: List[str],
        seed: int) -> int:
    """Demo loop: weighted scenario mix, rate-governed, until Ctrl+C."""
    rng = random.Random(seed)
    governor = RateGovernor()
    counters = {"sent": 0, "alerts": 0, "errors": 0}
    start = time.monotonic()
    base_interval = 1.0 / rate if rate > 0 else 0.0

    weights = [(s, MIX_WEIGHTS.get(s, 0.0)) for s in scenarios]
    total_weight = sum(w for _, w in weights) or 1.0

    print("ValiGuard traffic simulator")
    print(f"  API: {api_url.rstrip('/')}{ENDPOINT_PATH}")
    print(f"  scenarios: {', '.join(scenarios)} | rate: {rate:g} tx/s"
          + (f" | duration: {duration:g}s" if duration else ""))
    print("  Ctrl+C to stop.\n")

    try:
        while not duration or time.monotonic() - start < duration:
            roll = rng.uniform(0.0, total_weight)
            scenario = weights[-1][0]
            for name, weight in weights:
                if roll < weight:
                    scenario = name
                    break
                roll -= weight

            for payload in build_payloads(scenario, rng):
                governor.wait_for_slot()
                result = submit(api_url, payload)
                if result.status_code == 200:
                    counters["sent"] += 1
                    if result.severity in ("medium", "high", "critical"):
                        counters["alerts"] += 1
                    print(f"[{_now()}] {scenario:<11} "
                          f"{payload['amount']:>14,.2f} "
                          f"score={result.data.get('anomaly_score')} "
                          f"tier={result.severity}")
                else:
                    counters["errors"] += 1
                    print(f"[{_now()}] {scenario:<11} HTTP {result.status_code}")
                # Episode pacing vs. the configured base rate.
                if scenario in ("burst", "replay"):
                    time.sleep(EPISODE_INNER_DELAY)
                else:
                    time.sleep(base_interval)

            if duration and time.monotonic() - start >= duration:
                break
    except KeyboardInterrupt:
        print("\nSimulator stopped.")

    print(f"\nSummary: {counters['sent']} txs | "
          f"alert-tier (medium+): {counters['alerts']} | "
          f"errors: {counters['errors']}")
    return 0 if counters["errors"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ValiGuard HTTP traffic simulator")
    parser.add_argument("--api-url", default=DEFAULT_API_URL,
                        help="backend base URL (default: %(default)s)")
    parser.add_argument("--rate", type=float, default=0.8,
                        help="base txs/second for single-tx scenarios "
                             "(default: %(default)s)")
    parser.add_argument("--duration", type=float, default=0,
                        help="seconds to run (0 = until Ctrl+C)")
    parser.add_argument("--scenarios",
                        default=",".join(SCENARIOS),
                        help="comma-separated scenario subset (default: all)")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for reproducible runs (default: 42)")
    parser.add_argument("--verify", action="store_true",
                        help="one episode per scenario, print produced tiers, "
                             "exit nonzero on any target miss")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    invalid = [s for s in scenarios if s not in SCENARIOS]
    if invalid or not scenarios:
        print(f"Invalid scenarios: {', '.join(invalid)}", file=sys.stderr)
        return 2
    if args.rate < 0 or args.duration < 0:
        print("--rate and --duration must be non-negative", file=sys.stderr)
        return 2
    if args.verify:
        return verify(args.api_url, scenarios, args.seed)
    return run(args.api_url, args.rate, args.duration, scenarios, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
