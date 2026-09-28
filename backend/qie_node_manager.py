"""
qie_node_manager.py
Manager for QIE blockchain node interactions via Tendermint RPC.

This module provides functions to:
- Start/stop QIE nodes
- Query node health and validator status
- Broadcast transactions
- Monitor block synchronization

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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class QIENodeManager:
    """Manager for QIE node operations and RPC interactions."""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        chain_id: Optional[str] = None,
        moniker: Optional[str] = None,
        qie_home: Optional[str] = None,
        qied_binary: str = "qied"
    ):
        """
        Initialize QIE Node Manager.
        
        Args:
            rpc_url: RPC endpoint URL (default from QIE_RPC_URL env var or http://localhost:26657)
            chain_id: Chain ID (default from QIE_CHAIN_ID env var or qie_1990-1)
            moniker: Node moniker (default from QIE_MONIKER env var or valiguard-ai-validator)
            qie_home: QIE home directory (default from QIE_HOME env var or ~/.qieMainnetNode)
            qied_binary: Path to qied binary
        """
        self.rpc_url = rpc_url or os.getenv("QIE_RPC_URL", "http://localhost:26657")
        self.chain_id = chain_id or os.getenv("QIE_CHAIN_ID", "qie_1990-1")
        self.moniker = moniker or os.getenv("QIE_MONIKER", "valiguard-ai-validator")
        self.qie_home = qie_home or os.getenv("QIE_HOME", os.path.expanduser("~/.qieMainnetNode"))
        self.qied_binary = qied_binary
        
        self.node_process: Optional[subprocess.Popen] = None
        self.is_running = False
        
        # Setup resilient HTTP session with retries
        self.session = self._create_session()
        
        logger.info(f"QIE Node Manager initialized: rpc_url={self.rpc_url}, chain_id={self.chain_id}, moniker={self.moniker}")
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            backoff_factor=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def _rpc_call(self, method: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
        """
        Make a JSON-RPC call to the Tendermint RPC endpoint.
        
        Args:
            method: RPC method name (e.g., 'status', 'block')
            params: Optional parameters dict
            timeout: Request timeout in seconds
            
        Returns:
            Response data or empty dict on error
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
                    logger.error(f"RPC error for {method}: {data['error']}")
                    return {}
                
                return data.get("result", {})
                
            except Exception as inner_e:
                # Suppress all connection errors for demo stability
                logger.warning(f"RPC Connection failed for {method} (running in offline mode): {inner_e}")
                return {}

        except Exception as e:
            logger.error(f"Unexpected RPC error: {e}")
            return {}
    
    def start_qie_node(self) -> Dict[str, Any]:
        """
        Start a local QIE node with configured settings.
        
        Returns:
            Status dict with keys: success (bool), message (str), pid (int or None)
        """
        if self.is_running:
            logger.warning("Node is already running")
            return {
                "success": False,
                "message": "Node is already running",
                "pid": self.node_process.pid if self.node_process else None
            }
        
        try:
            logger.info(f"Starting QIE node (moniker: {self.moniker}, home: {self.qie_home})")
            
            # Ensure qie_home exists
            qie_path = Path(self.qie_home)
            qie_path.mkdir(parents=True, exist_ok=True)
            
            # Start the node
            self.node_process = subprocess.Popen(
                [self.qied_binary, "start", "--home", self.qie_home],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.is_running = True
            logger.info(f"Node started with PID {self.node_process.pid}")
            
            # Give node a moment to initialize
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
        """
        Gracefully stop the running QIE node.
        
        Args:
            timeout: Grace period before forcing termination (seconds)
            
        Returns:
            Status dict with keys: success (bool), message (str)
        """
        if not self.is_running or self.node_process is None:
            logger.warning("No running node to stop")
            return {
                "success": False,
                "message": "No running node process"
            }
        
        try:
            logger.info("Stopping QIE node gracefully")
            
            # Send SIGTERM for graceful shutdown
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
        """
        Check the health of the QIE node by querying status.
        
        Returns:
            Health status dict with keys:
                - healthy (bool): True if node is responding and synced
                - message (str): Status message
                - height (int): Current block height
                - sync_info (dict): Synchronization info
                - validator_info (dict): Validator info
        """
        try:
            status = self._rpc_call("status")
            
            if not status:
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
        """
        Get detailed node status from the RPC endpoint.
        
        Returns:
            Status dict containing node info, sync status, and validator info
        """
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
        """
        Get information about a specific validator.
        
        Args:
            validator_address: Validator address
            
        Returns:
            Validator info dict
        """
        try:
            # Query validator info from staking module
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
    
    def query_balance(self, address: str) -> Dict[str, Any]:
        """
        Query account balance from the blockchain.
        
        Args:
            address: Account address
            
        Returns:
            Balance info dict with keys: success (bool), balance (str), denom (str), message (str)
        """
        try:
            # Query account balance
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
            
            # Parse balance from response (structure may vary by chain)
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
        """
        Broadcast a signed transaction to the QIE network.
        
        Args:
            tx_dict: Transaction dictionary (must be signed and encoded)
            
        Returns:
            Broadcast result dict with keys:
                - success (bool): Transaction accepted
                - hash (str): Transaction hash
                - code (int): Transaction result code
                - message (str): Status message
        """
        try:
            # Serialize transaction to JSON string
            if isinstance(tx_dict, dict):
                tx_string = json.dumps(tx_dict)
            else:
                tx_string = str(tx_dict)
            
            # Broadcast via RPC
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
        """
        Get the latest block information.
        
        Returns:
            Block info dict
        """
        try:
            block = self._rpc_call("block", {})
            
            if not block:
                return {
                    "found": False,
                    "message": "Failed to retrieve latest block",
                    "data": {}
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
        """
        Wait for the node to sync with the network.
        
        Args:
            max_attempts: Maximum number of checks
            interval: Seconds between checks
            
        Returns:
            Sync result dict
        """
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


# Example usage and testing
if __name__ == "__main__":
    # Initialize manager
    manager = QIENodeManager()
    
    # Check node health
    print("Checking node health...")
    health = manager.check_node_health()
    print(f"Health: {json.dumps(health, indent=2)}")
    
    # Get node status
    print("\nGetting node status...")
    status = manager.get_node_status()
    print(f"Status: {json.dumps(status, indent=2)}")
    
    # Get latest block
    print("\nGetting latest block...")
    block = manager.get_latest_block()
    print(f"Block: {json.dumps(block, indent=2)}")
