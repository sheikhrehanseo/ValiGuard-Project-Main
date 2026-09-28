#!/usr/bin/env python
"""
ValiGuard AI traffic simulator.

Generates realistic bridge traffic against the running ValiGuard API so the
ingestion -> ML scoring -> alerting pipeline can be demoed without a live
QIE node. Every transaction is scored by the real Isolation Forest model
and persisted to the database (and pushed over the WebSocket feed).

Scenarios (--scenario):
    mix     weighted mix (default): mostly normal, some sweeps/bursts
    normal  ordinary transfer amounts
    sweep   huge value spikes (drives High/Critical severity tiers)
    burst   rapid-fire transfers from one window (frequency anomalies)
    replay  re-sends the same tx hash to demonstrate duplicate rejection

Examples:
    python scripts/generate_mock_traffic.py
    python scripts/generate_mock_traffic.py --rate 30 --duration 60
    python scripts/generate_mock_traffic.py --scenario sweep --rate 6
"""

import argparse
import random
import time
from datetime import datetime

import requests

DEFAULT_TARGET = "http://localhost:5000"
SOURCE_CHAINS = ["Ethereum", "BSC", "Polygon", "Avalanche", "QIE"]
DEST_CHAINS = ["QIE", "Ethereum", "BSC", "Polygon"]


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _random_hash() -> str:
    return "0x" + "".join(random.choice("0123456789abcdef") for _ in range(64))


def generate_tx(scenario: str) -> dict:
    """Build a validate-cross-chain payload for the given scenario."""
    if scenario == "sweep":
        amount = random.uniform(500_000, 5_000_000)
    elif scenario == "burst":
        amount = random.uniform(10, 500)
    else:
        amount = random.lognormvariate(5, 1)  # typical transfer amounts

    return {
        "transaction_hash": _random_hash(),
        "source_chain": random.choice(SOURCE_CHAINS),
        "dest_chain": random.choice(DEST_CHAINS),
        "amount": round(amount, 2),
    }


def send(endpoint: str, tx: dict, counters: dict) -> str:
    """POST one transaction and return a short human-readable result."""
    try:
        response = requests.post(endpoint, json=tx, timeout=10)
    except requests.RequestException as exc:
        counters["errors"] += 1
        return f"connection error ({type(exc).__name__})"

    if response.status_code == 409:
        counters["duplicates"] += 1
        return "duplicate rejected (409)"
    if response.status_code != 200:
        counters["errors"] += 1
        return f"error {response.status_code}"

    data = response.json().get("data", {})
    severity = data.get("severity")
    if severity in ("high", "critical"):
        counters["flagged"] += 1
    return f"score={data.get('anomaly_score')} severity={severity}"


def pick_scenario(anomaly_chance: float) -> str:
    """Weighted scenario roll for mix mode."""
    roll = random.random()
    if roll < anomaly_chance * 0.5:
        return "sweep"
    if roll < anomaly_chance:
        return "burst"
    return "normal"


def run(target: str, rate_per_min: float, duration_s: float,
        scenario: str, anomaly_chance: float) -> None:
    endpoint = f"{target.rstrip('/')}/api/v1/bridge/validate-cross-chain"
    counters = {"sent": 0, "flagged": 0, "duplicates": 0, "errors": 0}

    print("🚀 ValiGuard traffic simulator")
    print(f"   Target: {endpoint}")
    print(f"   Rate: {rate_per_min} tx/min • Scenario: {scenario}")
    if duration_s:
        print(f"   Duration: {duration_s}s")
    print("   Ctrl+C to stop.\n")

    delay = 60.0 / rate_per_min if rate_per_min > 0 else 2.0
    start = time.time()
    burst_left = 0
    replay_hash = None
    sent = 0

    try:
        while True:
            current = scenario if scenario != "mix" else pick_scenario(anomaly_chance)
            if current == "burst" and burst_left == 0:
                burst_left = random.randint(3, 6)  # rapid-fire window

            tx = generate_tx(current)
            if current == "replay" and replay_hash:
                tx["transaction_hash"] = replay_hash
                replay_hash = None  # second send of the same hash
            elif current == "replay":
                replay_hash = tx["transaction_hash"]

            result = send(endpoint, tx, counters)
            sent += 1
            print(f"[{_now()}] {result:<42s} {tx['transaction_hash'][:12]}…")

            if burst_left > 0:
                burst_left -= 1
                time.sleep(0.3)
            else:
                time.sleep(random.uniform(delay * 0.5, delay * 1.5))

            if duration_s and (time.time() - start) >= duration_s:
                break
    except KeyboardInterrupt:
        print("\n🛑 Simulator stopped.")

    print(f"\n📊 Summary: {sent} txs attempted | flagged(high/critical): "
          f"{counters['flagged']} | duplicates: {counters['duplicates']} | "
          f"errors: {counters['errors']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ValiGuard traffic simulator")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="API base URL")
    parser.add_argument("--rate", type=float, default=12.0,
                        help="transactions per minute (default 12)")
    parser.add_argument("--duration", type=float, default=0,
                        help="seconds to run (0 = run until Ctrl+C)")
    parser.add_argument("--scenario",
                        choices=["mix", "normal", "sweep", "burst", "replay"],
                        default="mix",
                        help="traffic scenario (default: weighted mix)")
    parser.add_argument("--anomaly-chance", type=float, default=0.15,
                        help="probability of an anomaly scenario per tx (mix mode)")
    args = parser.parse_args()
    run(args.target, args.rate, args.duration, args.scenario, args.anomaly_chance)


if __name__ == "__main__":
    main()
