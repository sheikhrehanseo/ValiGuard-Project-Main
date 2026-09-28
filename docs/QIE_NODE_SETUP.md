# QIE Node Setup & Management

This directory contains scripts and Python modules for setting up and managing a QIE blockchain validator node.

## Quick Start

### 1. Install QIE Node

```bash
bash scripts/install_qie.sh
```

This will:
- Download QIE v3 release from GitHub
- Extract the binary to `~/qie-node`
- Create configuration directory at `~/.qie`
- Set RPC port to 26657 and P2P port to 26656
- Enable CORS for local development

**Custom configuration:**
```bash
QIE_CHAIN_ID="qie_1990-1" \
QIE_MONIKER="my-validator" \
RPC_PORT=26657 \
P2P_PORT=26656 \
bash scripts/install_qie.sh
```

### 2. Initialize Node

```bash
bash scripts/init_qie_node.sh
```

This will:
- Create node directory structure at `~/.qieMainnetNode`
- Generate validator keys (`priv_validator_key.json`)
- Initialize genesis and configuration files

### 3. Configure Node

```bash
bash scripts/configure_qie_node.sh
```

This will:
- Copy genesis and config files from the QIE release
- Set the moniker (validator name)
- Configure RPC and P2P ports
- Enable CORS for local development

### 4. Complete Setup (All-in-One)

```bash
bash scripts/setup_qie_validator.sh
```

This runs all three scripts (install, init, configure) in sequence.

## Python QIE Node Manager

The `backend/qie_node_manager.py` module provides a Python interface to interact with your QIE node.

### Usage

```python
from qie_node_manager import QIENodeManager

# Initialize manager (reads from environment or uses defaults)
manager = QIENodeManager()

# Check node health
health = manager.check_node_health()
print(f"Healthy: {health['healthy']}, Height: {health['height']}")

# Get node status
status = manager.get_node_status()
print(status)

# Get latest block
block = manager.get_latest_block()
print(f"Latest block height: {block['height']}")

# Start/stop node
manager.start_qie_node()
# ... do things ...
manager.stop_qie_node()

# Wait for sync
sync_result = manager.wait_for_sync()
print(f"Synced: {sync_result['synced']}")

# Query balance
balance = manager.query_balance("qie1...")
print(f"Balance: {balance['balance']} {balance['denom']}")

# Broadcast transaction
tx_result = manager.broadcast_transaction(tx_dict)
print(f"TX Hash: {tx_result['hash']}")
```

### Environment Variables

The manager reads from environment variables:

```bash
export QIE_RPC_URL="http://localhost:26657"        # RPC endpoint (default)
export QIE_CHAIN_ID="qie_1990-1"                   # Chain ID (default)
export QIE_MONIKER="valiguard-ai-validator"      # Node moniker (default)
export QIE_HOME="$HOME/.qieMainnetNode"            # Node home directory (default)
```

Or load from `.env`:

```bash
# .env file
QIE_RPC_URL=http://localhost:26657
QIE_CHAIN_ID=qie_1990-1
QIE_MONIKER=valiguard-ai-validator
QIE_HOME=/home/user/.qieMainnetNode
```

### Available Methods

#### Node Lifecycle

- `start_qie_node()` - Start the QIE node
- `stop_qie_node(timeout=10)` - Stop the running node
- `check_node_health()` - Check if node is healthy and synced
- `wait_for_sync(max_attempts=60, interval=5)` - Wait for node to sync

#### Node Queries

- `get_node_status()` - Get detailed node status
- `get_latest_block()` - Get the latest block information
- `get_validator_info(validator_address)` - Get validator information
- `query_balance(address)` - Query account balance

#### Transactions

- `broadcast_transaction(tx_dict)` - Broadcast a signed transaction to the network

### Error Handling

All methods return dictionaries with structured responses:

```python
{
    "success": bool,
    "message": str,
    "data": dict,  # Additional data (varies by method)
}
```

The module includes:
- Automatic retry logic with exponential backoff
- Connection error handling
- Timeout management
- Comprehensive logging

## Running Tests

```bash
cd backend
python test_qie_node_manager.py
```

This will test:
- Manager initialization
- Node health checks
- Node status queries
- Block retrieval
- Validator info queries
- Balance queries
- Transaction broadcast handling

**Note:** Some tests will fail if the node is not running. Start the node first:

```bash
qied start --home ~/.qieMainnetNode
```

## Starting Your Validator Node

### 1. Create Validator Keys

```bash
qied keys add validator --home ~/.qieMainnetNode
```

Save the seed phrase securely!

### 2. Start the Node

```bash
qied start --home ~/.qieMainnetNode
```

The node will start syncing with the network. This may take time depending on network size.

### 3. Monitor Sync Status

```bash
# Via RPC
curl http://localhost:26657/status | jq .

# Via Python
python -c "from qie_node_manager import QIENodeManager; print(QIENodeManager().check_node_health())"
```

### 4. Become a Validator (Once Synced)

Once your node is synced, you can stake and become a validator:

```bash
qied tx staking create-validator \
  --moniker="<your-name>" \
  --amount=1000000aqie \
  --pubkey=$(qied tendermint show-validator --home ~/.qieMainnetNode) \
  --from=validator \
  --home ~/.qieMainnetNode \
  --chain-id=qie_1990-1
```

## Troubleshooting

### Node not responding to RPC

```bash
# Check if node is running
ps aux | grep qied

# Check RPC endpoint
curl http://localhost:26657/status

# Check node logs
tail -f ~/.qieMainnetNode/log
```

### Port conflicts

If ports 26657 or 26656 are already in use:

```bash
bash scripts/configure_qie_node.sh RPC_PORT=26668 P2P_PORT=26666
```

### Syncing stuck

```bash
# Check sync status
curl http://localhost:26657/status | jq '.result.sync_info'

# Reset node state (careful!)
qied tendermint unsafe-reset-all --home ~/.qieMainnetNode
```

## File Structure

```
scripts/
  ├── install_qie.sh          # Download and install QIE binary
  ├── init_qie_node.sh         # Initialize node directory structure
  ├── configure_qie_node.sh    # Configure node settings
  └── setup_qie_validator.sh   # All-in-one setup script

backend/
  ├── qie_node_manager.py      # Main Python module
  └── test_qie_node_manager.py # Test suite
```

## References

- [QIE Documentation](https://docs.qie.digital)
- [How to Become a Validator on QIE V3](https://docs.qie.digital/how-to-become-a-validator-on-qie-v3)
- [Tendermint RPC Documentation](https://docs.tendermint.com/v0.38/rpc/)

## Notes

- Always back up your validator keys securely
- Keep your node's private key safe (`~/.qieMainnetNode/config/priv_validator_key.json`)
- Use only trusted RPC endpoints
- Test all scripts in a development environment first
- Monitor your node regularly for sync issues and performance

