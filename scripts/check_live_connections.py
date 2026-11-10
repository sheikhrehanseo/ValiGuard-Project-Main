"""Read-only checks of the configured QIE connections; never opens the app or DB."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
import requests

ROOT = Path(__file__).resolve().parents[1]


def check_connection(name, url, timeout, method=None, params=None, validate=None):
    """Report transport, protocol and response-shape errors separately from empty data."""
    parsed = urlsplit(url)
    result = {"check": name, "host": parsed.hostname}
    try:
        if method:
            response = requests.post(url, json={
                "jsonrpc": "2.0", "id": 1, "method": method,
                "params": params if params is not None else [],
            }, timeout=timeout)
        else:
            response = requests.get(url, timeout=timeout)
        result["http_status"] = response.status_code
        response.raise_for_status()
        body = response.json()
        if method:
            if not isinstance(body, dict) or body.get("error") or "result" not in body:
                raise ValueError("RPC method unavailable or invalid JSON-RPC response")
            body = body["result"]
        result["data"] = validate(body) if validate else {"available": body is not None}
        result["ok"] = True
    except requests.exceptions.SSLError:
        result.update(ok=False, error="TLS certificate verification failed")
    except requests.RequestException as exc:
        # Avoid printing URLs with credentials, API keys or response content.
        result.update(ok=False, error=type(exc).__name__)
    except (ValueError, TypeError, KeyError) as exc:
        result.update(ok=False, error=str(exc))
    return result


def require_chain(actual, expected):
    if actual != expected:
        raise ValueError(f"Wrong chain: expected {expected}, received {actual}")
    return {"chain_id": actual}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    load_dotenv(ROOT / ".env")
    rpc = os.getenv("QIE_RPC_URL", "http://localhost:26657").rstrip("/")
    evm = os.getenv("QIE_EVM_RPC_URL", "http://localhost:8545")
    explorer = os.getenv("QIE_EXPLORER_API_URL", "https://mainnet.qie.digital/api/v2").rstrip("/")
    rest = os.getenv("QIE_COSMOS_REST_URL", "https://rest.cosmos.directory/qie").rstrip("/")
    chain_id = os.getenv("QIE_CHAIN_ID", "qie_1990-1")
    evm_chain_id = int(chain_id.split("_", 1)[1].split("-", 1)[0])

    def status(data):
        result = require_chain(data["node_info"]["network"], chain_id)
        result.update(height=int(data["sync_info"]["latest_block_height"]),
                      syncing=bool(data["sync_info"]["catching_up"]))
        return result

    def block(data):
        require_chain(data["block"]["header"]["chain_id"], chain_id)
        return {"height": int(data["block"]["header"]["height"]),
                "transactions": len(data["block"]["data"].get("txs") or [])}

    def evm_block(data):
        if not isinstance(data, dict):
            raise ValueError("EVM block unavailable")
        return {"height": int(data["number"], 16) if data.get("number") else None,
                "transactions": len(data.get("transactions") or [])}

    def explorer_items(data):
        items = data if isinstance(data, list) else data.get("items")
        if not isinstance(items, list):
            raise ValueError("Explorer transaction list unavailable")
        return {"transactions": len(items)}

    checks = [
        ("tendermint_status", rpc, "status", {}, status),
        ("tendermint_block", rpc, "block", {}, block),
        ("tendermint_mempool", rpc, "unconfirmed_txs", {},
         lambda d: {"pending": int(d["n_txs"])}),
        ("tendermint_validators", rpc, "validators", {"page": "1", "per_page": "100"},
         lambda d: {"validators": int(d["total"])}),
        ("evm_chain", evm, "eth_chainId", [],
         lambda d: require_chain(int(d, 16), evm_chain_id)),
        ("evm_block", evm, "eth_getBlockByNumber", ["latest", True], evm_block),
        ("evm_pending", evm, "eth_getBlockByNumber", ["pending", True], evm_block),
        ("evm_balance", evm, "eth_getBalance", ["0x" + "0" * 40, "latest"],
         lambda d: {"balance_wei": str(int(d, 16))}),
        ("explorer_transactions", explorer + "/main-page/transactions", None, None, explorer_items),
        ("staking_validators", rest + "/cosmos/staking/v1beta1/validators?pagination.limit=200",
         None, None, lambda d: {"validators": len(d["validators"])}),
    ]

    def run(check):
        name, url, method, params, validate = check
        return check_connection(name, url, args.timeout, method, params, validate)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(run, checks))
    print(json.dumps({"expected_chain": chain_id, "checks": results}, indent=2))
    return 0 if all(result["ok"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
