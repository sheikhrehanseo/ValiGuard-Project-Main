"""
qie_node_manager.py
Manager for QIE blockchain node interactions via Tendermint RPC and Standard EVM JSON-RPC.

This module provides functions to:
- Start/stop QIE nodes
- Query node health and validator status (Tendermint RPC & EVM JSON-RPC)
- Fetch pending mempool and confirmed block transactions across Tendermint & EVM RPC
- Query account balances and broadcast transactions

Reference: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3
"""

import os
import json
import logging
import subprocess
import time
import signal
from typing import Dict, Optional, Any, List
from pathlib import Path
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dotenv import load_dotenv

# Suppress InsecureRequestWarning when falling back on self-signed/incomplete RPC SSL chains
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class QIENodeManager:
    """Manager for QIE node operations, Tendermint RPC, and Standard EVM JSON-RPC interactions."""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        chain_id: Optional[str] = None,
        moniker: Optional[str] = None,
        qie_home: Optional[str] = None,
        qied_binary: str = "qied",
        evm_rpc_url: Optional[str] = None,
    ):
        """
        Initialize QIE Node Manager.
        
        Args:
            rpc_url: Tendermint RPC endpoint URL (default from QIE_RPC_URL env var or http://localhost:26657)
            chain_id: Chain ID (default from QIE_CHAIN_ID env var or qie_1990-1)
            moniker: Node moniker (default from QIE_MONIKER env var or valiguard-ai-validator)
            qie_home: QIE home directory (default from QIE_HOME env var or ~/.qieMainnetNode)
            qied_binary: Path to qied binary
            evm_rpc_url: Standard EVM JSON-RPC endpoint URL (default from QIE_EVM_RPC_URL env var or http://localhost:8545)
        """
        self.rpc_url = rpc_url or os.getenv("QIE_RPC_URL", "http://localhost:26657")
        self.evm_rpc_url = evm_rpc_url or os.getenv("QIE_EVM_RPC_URL", "http://localhost:8545")
        self.chain_id = chain_id or os.getenv("QIE_CHAIN_ID", "qie_1990-1")
        self.moniker = moniker or os.getenv("QIE_MONIKER", "valiguard-ai-validator")
        self.qie_home = qie_home or os.getenv("QIE_HOME", os.path.expanduser("~/.qieMainnetNode"))
        self.qied_binary = qied_binary
        
        self.node_process: Optional[subprocess.Popen] = None
        self.is_running = False
        self._validator_set_cache: Dict[str, Any] = {"result": None, "fetched_at": 0.0}
        
        # Setup resilient HTTP session with retries
        self.session = self._create_session()
        
        logger.info(
            f"QIE Node Manager initialized: rpc_url={self.rpc_url}, "
            f"evm_rpc_url={self.evm_rpc_url}, chain_id={self.chain_id}, moniker={self.moniker}"
        )
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic and SSL tolerance for public RPCs."""
        session = requests.Session()
        session.verify = False
        retry_strategy = Retry(
            total=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            backoff_factor=0.5
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def _rpc_call(self, method: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
        """
        Make a JSON-RPC call to the Tendermint RPC endpoint.
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params or {}
            }
            
            try:
                response = self.session.post(
                    self.rpc_url,
                    json=payload,
                    timeout=timeout
                )
                response.raise_for_status()
                
                data = response.json()
                if "error" in data and data["error"]:
                    logger.debug(f"RPC error for {method}: {data['error']}")
                    return {}

                return data.get("result", {})
                
            except Exception as inner_e:
                logger.debug(f"RPC Connection failed for {method} (running in offline mode): {inner_e}")
                return {}

        except Exception as e:
            logger.error(f"Unexpected RPC error: {e}")
            return {}

    def rpc_call(
        self,
        method: str,
        params: Optional[Dict] = None,
        timeout: int = 3,
    ) -> Dict[str, Any]:
        """Expose a bounded Tendermint RPC call for ingestion and other runtime services."""
        return self._rpc_call(method, params=params, timeout=timeout)

    def _evm_rpc_call(
        self,
        method: str,
        params: Optional[List[Any]] = None,
        timeout: int = 3,
        use_session: bool = False,
    ) -> Any:
        """
        Make a standard Ethereum JSON-RPC 2.0 call to the QIE EVM RPC endpoint.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params if params is not None else [],
        }
        http_client = self.session if use_session else requests
        try:
            try:
                response = http_client.post(
                    self.evm_rpc_url,
                    json=payload,
                    timeout=timeout,
                )
            except requests.exceptions.SSLError:
                response = http_client.post(
                    self.evm_rpc_url,
                    json=payload,
                    timeout=timeout,
                    verify=False,
                )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                if data.get("error"):
                    logger.debug(f"EVM RPC error for {method}: {data['error']}")
                    return None
                return data.get("result")
            return None
        except Exception as exc:
            logger.debug(f"EVM RPC connection failed for {method}: {exc}")
            return None

    def evm_rpc_call(
        self,
        method: str,
        params: Optional[List[Any]] = None,
        timeout: int = 3,
    ) -> Any:
        """Expose a bounded one-shot EVM JSON-RPC call for runtime services."""
        return self._evm_rpc_call(method, params=params, timeout=timeout, use_session=False)

    def get_evm_block_number(self, timeout: int = 3) -> Optional[int]:
        """Query the latest block height via standard EVM eth_blockNumber."""
        result = self.evm_rpc_call("eth_blockNumber", [], timeout=timeout)
        if isinstance(result, str) and result.startswith(("0x", "0X")):
            try:
                return int(result, 16)
            except ValueError:
                return None
        if isinstance(result, int):
            return result
        return None

    def get_evm_latest_block(
        self, full_transactions: bool = True, timeout: int = 3
    ) -> Dict[str, Any]:
        """
        Get the latest block and its transactions via standard EVM eth_getBlockByNumber.
        """
        block = self.evm_rpc_call(
            "eth_getBlockByNumber", ["latest", full_transactions], timeout=timeout
        )
        if not isinstance(block, dict):
            return {
                "found": False,
                "message": "Failed to retrieve latest EVM block",
                "data": {},
                "height": 0,
                "transactions": [],
            }

        raw_number = block.get("number")
        try:
            height = int(raw_number, 16) if isinstance(raw_number, str) else int(raw_number or 0)
        except (ValueError, TypeError):
            height = 0

        raw_ts = block.get("timestamp")
        iso_ts: Optional[str] = None
        if raw_ts is not None:
            try:
                ts_int = int(raw_ts, 16) if isinstance(raw_ts, str) else int(raw_ts)
                iso_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_int))
            except (ValueError, TypeError, OSError):
                iso_ts = None

        txs = block.get("transactions") or []
        return {
            "found": True,
            "message": "Latest EVM block retrieved successfully",
            "data": block,
            "height": height,
            "timestamp": iso_ts,
            "transactions": txs if isinstance(txs, list) else [],
        }

    def get_evm_pending_transactions(self, timeout: int = 3) -> List[Dict[str, Any]]:
        """
        Fetch pending mempool transactions via standard EVM JSON-RPC.
        """
        pending_block = self.evm_rpc_call(
            "eth_getBlockByNumber", ["pending", True], timeout=timeout
        )
        if isinstance(pending_block, dict):
            txs = pending_block.get("transactions") or []
            dict_txs = [tx for tx in txs if isinstance(tx, dict)]
            if dict_txs:
                return dict_txs

        txpool = self.evm_rpc_call("txpool_content", [], timeout=timeout)
        if isinstance(txpool, dict):
            pending_map = txpool.get("pending") or {}
            flattened: List[Dict[str, Any]] = []
            if isinstance(pending_map, dict):
                for nonce_map in pending_map.values():
                    if isinstance(nonce_map, dict):
                        for tx in nonce_map.values():
                            if isinstance(tx, dict):
                                flattened.append(tx)
            return flattened

        return []

    def get_evm_transaction(self, tx_hash: str, timeout: int = 3) -> Dict[str, Any]:
        """Fetch a single transaction by hash via EVM eth_getTransactionByHash."""
        tx = self.evm_rpc_call("eth_getTransactionByHash", [tx_hash], timeout=timeout)
        if isinstance(tx, dict):
            return {"found": True, "data": tx, "message": "Transaction found"}
        return {"found": False, "data": {}, "message": "Transaction not found"}

    def query_evm_balance(self, address: str, timeout: int = 3) -> Dict[str, Any]:
        """Query a 0x account balance via standard EVM eth_getBalance."""
        result = self.evm_rpc_call("eth_getBalance", [address, "latest"], timeout=timeout)
        if isinstance(result, str) and result.startswith(("0x", "0X")):
            try:
                wei_val = int(result, 16)
                return {
                    "success": True,
                    "balance": str(wei_val),
                    "denom": "aqie",
                    "message": "Balance retrieved successfully via EVM RPC",
                }
            except ValueError:
                pass
        return {
            "success": False,
            "balance": "0",
            "denom": "aqie",
            "message": "Address not found or EVM RPC unavailable",
        }

    def broadcast_evm_transaction(self, raw_tx_hex: str, timeout: int = 10) -> Dict[str, Any]:
        """Broadcast a signed raw hex transaction via standard EVM eth_sendRawTransaction."""
        tx_hash = self._evm_rpc_call(
            "eth_sendRawTransaction", [raw_tx_hex], timeout=timeout, use_session=True
        )
        if isinstance(tx_hash, str) and tx_hash.startswith(("0x", "0X")):
            return {
                "success": True,
                "hash": tx_hash,
                "code": 0,
                "message": "EVM transaction accepted",
            }
        return {
            "success": False,
            "hash": "",
            "code": -1,
            "message": "EVM broadcast failed; no valid response from RPC",
        }
    
    def start_qie_node(self) -> Dict[str, Any]:
        """Start a local QIE node with configured settings."""
        if self.is_running:
            logger.warning("Node is already running")
            return {
                "success": False,
                "message": "Node is already running",
                "pid": self.node_process.pid if self.node_process else None
            }
        
        try:
            logger.info(f"Starting QIE node (moniker: {self.moniker}, home: {self.qie_home})")
            qie_path = Path(self.qie_home)
            qie_path.mkdir(parents=True, exist_ok=True)
            
            self.node_process = subprocess.Popen(
                [self.qied_binary, "start", "--home", self.qie_home],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.is_running = True
            logger.info(f"Node started with PID {self.node_process.pid}")
            time.sleep(2)
            
            return {
                "success": True,
                "message": "Node started successfully",
                "pid": self.node_process.pid
            }
        except FileNotFoundError:
            logger.error(f"qied binary not found: {self.qied_binary}")
            return {
                "success": False,
                "message": f"qied binary not found at {self.qied_binary}",
                "pid": None
            }
        except Exception as e:
            logger.error(f"Failed to start node: {e}")
            self.is_running = False
            return {
                "success": False,
                "message": f"Failed to start node: {str(e)}",
                "pid": None
            }
    
    def stop_qie_node(self, timeout: int = 10) -> Dict[str, Any]:
        """Gracefully stop the running QIE node."""
        if not self.is_running or self.node_process is None:
            logger.warning("No running node to stop")
            return {
                "success": False,
                "message": "No running node process"
            }
        
        try:
            logger.info("Stopping QIE node gracefully")
            self.node_process.send_signal(signal.SIGTERM)
            
            try:
                self.node_process.wait(timeout=timeout)
                logger.info("Node stopped gracefully")
            except subprocess.TimeoutExpired:
                logger.warning(f"Node did not stop within {timeout}s, forcing termination")
                self.node_process.kill()
                self.node_process.wait()
                logger.info("Node forcefully terminated")
            
            self.is_running = False
            return {
                "success": True,
                "message": "Node stopped successfully"
            }
        except Exception as e:
            logger.error(f"Error stopping node: {e}")
            return {
                "success": False,
                "message": f"Error stopping node: {str(e)}"
            }
    
    def check_node_health(self) -> Dict[str, Any]:
        """Check the health of the QIE node by querying status."""
        try:
            status = self._rpc_call("status")
            
            if not status:
                evm_height = self.get_evm_block_number(timeout=3)
                if evm_height is not None and evm_height > 0:
                    return {
                        "healthy": True,
                        "message": "Node is healthy (via EVM RPC)",
                        "height": evm_height,
                        "sync_info": {"latest_block_height": str(evm_height), "catching_up": False},
                        "validator_info": {}
                    }
                return {
                    "healthy": False,
                    "message": "Node is not responding to RPC calls",
                    "height": 0,
                    "sync_info": {},
                    "validator_info": {}
                }
            
            sync_info = status.get("sync_info", {})
            validator_info = status.get("validator_info", {})
            
            height = int(sync_info.get("latest_block_height", 0))
            catching_up = sync_info.get("catching_up", False)
            
            healthy = not catching_up and height > 0
            
            message = "Node is healthy" if healthy else "Node is syncing or not responding"
            if catching_up:
                message = f"Node is syncing (height: {height})"
            
            logger.info(f"Node health check: {message}")
            
            return {
                "healthy": healthy,
                "message": message,
                "height": height,
                "sync_info": sync_info,
                "validator_info": validator_info
            }
        except Exception as e:
            logger.error(f"Error checking node health: {e}")
            return {
                "healthy": False,
                "message": f"Error checking health: {str(e)}",
                "height": 0,
                "sync_info": {},
                "validator_info": {}
            }
    
    def get_node_status(self) -> Dict[str, Any]:
        """Get detailed node status from the RPC endpoint."""
        try:
            status = self._rpc_call("status")
            
            if not status:
                return {
                    "online": False,
                    "message": "Node is not responding",
                    "data": {}
                }
            
            return {
                "online": True,
                "message": "Node status retrieved successfully",
                "data": status
            }
        except Exception as e:
            logger.error(f"Error getting node status: {e}")
            return {
                "online": False,
                "message": f"Error: {str(e)}",
                "data": {}
            }
    
    def get_validator_info(self, validator_address: str) -> Dict[str, Any]:
        """Get information about a specific validator."""
        try:
            query_result = self._rpc_call(
                "abci_query",
                {
                    "path": f"/custom/staking/validator/{validator_address}",
                    "data": "",
                    "prove": False
                }
            )
            
            if not query_result:
                return {
                    "found": False,
                    "message": "Validator not found",
                    "data": {}
                }
            
            return {
                "found": True,
                "message": "Validator found",
                "data": query_result
            }
        except Exception as e:
            logger.error(f"Error getting validator info: {e}")
            return {
                "found": False,
                "message": f"Error: {str(e)}",
                "data": {}
            }

    def get_validator_set(
        self, per_page: int = 100, max_pages: int = 100
    ) -> Dict[str, Any]:
        """Get the validator set from Tendermint's paginated GET endpoint (cached for 30s)."""
        if ":26657" not in self.rpc_url and "qie.test" not in self.rpc_url:
            return {
                "success": False,
                "validators": [],
                "block_height": 0,
                "total": 0,
                "message": "Tendermint /validators endpoint not exposed on public EVM gateway",
            }
        now = time.time()
        if (
            per_page == 100
            and self._validator_set_cache["result"] is not None
            and now - self._validator_set_cache["fetched_at"] < 30.0
        ):
            return self._validator_set_cache["result"]

        validators: List[Dict[str, Any]] = []
        block_height = 0
        base_url = self.rpc_url.rstrip("/")

        try:
            for page in range(1, max_pages + 1):
                try:
                    response = requests.get(
                        f"{base_url}/validators",
                        params={"page": page, "per_page": per_page},
                        timeout=3,
                    )
                except requests.exceptions.SSLError:
                    response = requests.get(
                        f"{base_url}/validators",
                        params={"page": page, "per_page": per_page},
                        timeout=3,
                        verify=False,
                    )
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result", payload) or {}
                page_validators = result.get("validators") or []
                validators.extend(page_validators)
                block_height = int(result.get("block_height", block_height) or 0)

                total = int(
                    result.get("total", result.get("count_total", 0)) or 0
                )
                if (
                    not page_validators
                    or len(validators) >= total > 0
                    or len(page_validators) < per_page
                ):
                    break

            res = {
                "success": True,
                "validators": validators,
                "block_height": block_height,
                "total": len(validators),
                "message": "Validator set retrieved successfully",
            }
            if per_page == 100:
                self._validator_set_cache = {"result": res, "fetched_at": now}
            return res
        except Exception as e:
            logger.debug(f"Unable to retrieve validator set: {e}")
            res = {
                "success": False,
                "validators": [],
                "block_height": block_height,
                "total": 0,
                "message": f"Validator set unavailable: {e}",
            }
            if per_page == 100:
                self._validator_set_cache = {"result": res, "fetched_at": now}
            return res
    
    def query_balance(self, address: str) -> Dict[str, Any]:
        """Query account balance from the blockchain (supports Cosmos qie1... and EVM 0x... addresses)."""
        try:
            if isinstance(address, str) and address.startswith(("0x", "0X")):
                evm_res = self.query_evm_balance(address)
                if evm_res.get("success"):
                    return evm_res

            query_result = self._rpc_call(
                "abci_query",
                {
                    "path": f"/custom/bank/balances/{address}",
                    "data": "",
                    "prove": False
                }
            )
            
            if not query_result:
                return {
                    "success": False,
                    "balance": "0",
                    "denom": "aqie",
                    "message": "Address not found or no balance"
                }
            
            response_data = query_result.get("response", {})
            value = response_data.get("value", "")
            
            logger.info(f"Balance query for {address}: {value}")
            
            return {
                "success": True,
                "balance": value,
                "denom": "aqie",
                "message": "Balance retrieved successfully"
            }
        except Exception as e:
            logger.error(f"Error querying balance: {e}")
            return {
                "success": False,
                "balance": "0",
                "denom": "aqie",
                "message": f"Error: {str(e)}"
            }
    
    def broadcast_transaction(self, tx_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Broadcast a signed transaction to the QIE network (Tendermint RPC or EVM raw hex)."""
        try:
            if isinstance(tx_dict, str) and tx_dict.startswith(("0x", "0X")):
                return self.broadcast_evm_transaction(tx_dict)
            if isinstance(tx_dict, dict) and isinstance(tx_dict.get("raw_tx"), str) and tx_dict["raw_tx"].startswith(("0x", "0X")):
                return self.broadcast_evm_transaction(tx_dict["raw_tx"])

            if isinstance(tx_dict, dict):
                tx_string = json.dumps(tx_dict)
            else:
                tx_string = str(tx_dict)
            
            broadcast_result = self._rpc_call(
                "broadcast_tx_sync",
                {"tx": tx_string}
            )
            
            if not broadcast_result:
                return {
                    "success": False,
                    "hash": "",
                    "code": -1,
                    "message": "Broadcast failed; no response from RPC"
                }
            
            code = broadcast_result.get("code", 0)
            hash_value = broadcast_result.get("hash", "")
            log_msg = broadcast_result.get("log", "")
            
            success = code == 0
            
            logger.info(f"Transaction broadcast {'successful' if success else 'failed'}: hash={hash_value}, code={code}")
            
            return {
                "success": success,
                "hash": hash_value,
                "code": code,
                "message": log_msg or ("Transaction accepted" if success else "Transaction rejected")
            }
        except Exception as e:
            logger.error(f"Error broadcasting transaction: {e}")
            return {
                "success": False,
                "hash": "",
                "code": -1,
                "message": f"Error: {str(e)}"
            }
    
    def get_latest_block(self) -> Dict[str, Any]:
        """Get the latest block information."""
        try:
            block = self._rpc_call("block", {})
            
            if not block:
                return {
                    "found": False,
                    "message": "Failed to retrieve latest block",
                    "data": {},
                    "height": 0
                }
            
            block_data = block.get("block", {})
            block_height = block_data.get("header", {}).get("height", "0")
            
            logger.info(f"Latest block height: {block_height}")
            
            return {
                "found": True,
                "message": "Latest block retrieved successfully",
                "data": block,
                "height": int(block_height) if block_height else 0
            }
        except Exception as e:
            logger.error(f"Error getting latest block: {e}")
            return {
                "found": False,
                "message": f"Error: {str(e)}",
                "data": {},
                "height": 0
            }
    
    def wait_for_sync(self, max_attempts: int = 60, interval: int = 5) -> Dict[str, Any]:
        """Wait for the node to sync with the network."""
        logger.info(f"Waiting for node to sync (max {max_attempts} attempts, {interval}s interval)")
        
        for attempt in range(max_attempts):
            health = self.check_node_health()
            
            if health["healthy"]:
                logger.info(f"Node synced after {attempt + 1} attempts")
                return {
                    "synced": True,
                    "message": "Node synced successfully",
                    "attempts": attempt + 1,
                    "height": health["height"]
                }
            
            if attempt < max_attempts - 1:
                logger.info(f"Sync attempt {attempt + 1}/{max_attempts}: height={health['height']}")
                time.sleep(interval)
        
        health = self.check_node_health()
        return {
            "synced": False,
            "message": "Node did not sync within timeout",
            "attempts": max_attempts,
            "height": health["height"]
        }