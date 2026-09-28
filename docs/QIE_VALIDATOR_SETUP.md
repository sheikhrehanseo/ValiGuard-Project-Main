# QIE Validator Node Setup & Wallet Management Guide

## 📋 Overview

This guide covers the complete process for setting up a QIE Mainnet validator node, including:
1. Installation of QIE binary
2. Node initialization and configuration
3. Starting the node and waiting for sync
4. Creating validator wallet
5. Wallet management and operations

## 🚀 Quick Start (Automated)

The fastest way to get started is using the orchestrator script:

```bash
bash scripts/run_validator_setup.sh
```

This runs all steps sequentially with proper error handling and user prompts.

---

## 📝 Manual Step-by-Step Process

### Prerequisites

- **OS**: Linux (Ubuntu 20.04+), macOS, or Windows (WSL2/Git Bash)
- **Disk Space**: Minimum 60GB for full node
- **RAM**: 8GB+ recommended
- **Internet**: Stable, high-speed connection recommended
- **Tools**: bash, curl, screen (for Linux)

### Step 1: Install QIE Binary

Downloads and installs the QIE v3 binary from official GitHub releases.

```bash
bash scripts/install_qie.sh
```

**Output:**
```
✓ QIE v3.0.0 binary installed
✓ Location: ~/.qie/qied
```

**What it does:**
- Downloads QIE v3 from GitHub releases
- Validates checksum for security
- Makes binary executable
- Creates symlink in PATH

### Step 2: Initialize Node

Initializes the node directory structure and generates validator keys.

```bash
bash scripts/init_qie_node.sh
```

**Output:**
```
✓ Node directory created: ~/.qieMainnetNode
✓ Validator key generated: priv_validator_key.json
✓ Node ID: <validator_id>
```

**What it does:**
- Creates `~/.qieMainnetNode` directory
- Initializes node with `qied init`
- Generates private validator key
- Sets up config.toml structure

**Important:** Save your validator ID and key securely!

### Step 3: Configure Node

Applies genesis file, sets moniker, and configures RPC/P2P ports.

```bash
bash scripts/configure_qie_node.sh
```

**Configuration Details:**
- **Moniker**: `valiguard-ai-validator` (or your custom name)
- **RPC Port**: 26657 (for queries)
- **P2P Port**: 26656 (for peer connections)
- **Genesis**: Downloads from official QIE repository
- **CORS**: Enabled for local development

### Step 4: Start Node & Wait for Sync

Starts the QIE node and waits for it to sync with the network.

```bash
bash scripts/start_qie_node.sh
```

**Process:**
- Starts node in background (screen session on Linux, background on Windows)
- Monitors sync status via RPC endpoint
- Waits until `catching_up: false`
- Shows current block height

**Duration:** 10-30 minutes depending on network speed

**Viewing Logs:**
- **Linux/macOS**: `screen -r qie-node` or `tail -f ~/.qieMainnetNode/qie.log`
- **Windows**: `Get-Content ~/.qieMainnetNode/qie.log -Tail 50 -Wait`

**Check Status:**
```bash
curl http://localhost:26657/status
```

Expected output when synced:
```json
{
  "result": {
    "sync_info": {
      "catching_up": false,
      "latest_block_height": "1234567"
    }
  }
}
```

### Step 5: Create Validator Wallet

Creates a new wallet for validator operations.

```bash
bash scripts/create_wallet.sh validator
```

**Interactive Process:**
- Prompts for wallet password (required for signing transactions)
- Creates keypair in `~/.qieMainnetNode/keyring-test`
- Returns wallet address, public key, and private key

**Output:**
```
Wallet Name: validator
Address: qie19y2ul696lc6lz640pldete7h7jzdc0xj32wt6j
Public Key: {"@type":"/ethermint.crypto.v1.ethsecp256k1.PubKey",...}
```

**Security:**
- ⚠️ **IMPORTANT**: Save your password securely - you cannot recover it!
- Back up the wallet info file: `~/.qieMainnetNode/wallet_info.txt`
- Never share your private key

---

## 💼 Wallet Management

### Using CLI Commands

#### List all wallets:
```bash
~/.qie/qied keys list --home ~/.qieMainnetNode
```

#### Get wallet details:
```bash
~/.qie/qied keys show validator --home ~/.qieMainnetNode
```

#### Get account balance:
```bash
~/.qie/qied query bank balances qie19y2ul696lc6lz640pldete7h7jzdc0xj32wt6j --home ~/.qieMainnetNode
```

### Using Python Wallet Manager

The `backend/qie_wallet_manager.py` provides a Python interface for wallet operations:

#### List wallets:
```bash
python backend/qie_wallet_manager.py list
```

#### Get wallet info:
```bash
python backend/qie_wallet_manager.py info validator
```

#### Query balance:
```bash
python backend/qie_wallet_manager.py balance qie19y2ul696lc6lz640pldete7h7jzdc0xj32wt6j
```

#### Get all validators:
```bash
python backend/qie_wallet_manager.py validators
```

#### Get node status:
```bash
python backend/qie_wallet_manager.py status
```

#### Export wallet info:
```bash
python backend/qie_wallet_manager.py export validator validator_backup.json
```

### Integration with Flask API

The Flask API (`backend/app.py`) provides REST endpoints for wallet operations:

```bash
# Get QIE node status (includes sync info)
curl http://localhost:5000/api/v1/qie/node/status

# Get validator info
curl -H "X-API-Key: your-key" \
  http://localhost:5000/api/v1/qie/validator/info?address=qie19y2ul696lc6lz640pldete7h7jzdc0xj32wt6j

# Get account balance
curl -H "X-API-Key: your-key" \
  http://localhost:5000/api/v1/qie/account/qie19y2ul696lc6lz640pldete7h7jzdc0xj32wt6j

# Broadcast transaction
curl -X POST http://localhost:5000/api/v1/qie/transaction/broadcast \
  -H "Content-Type: application/json" \
  -d '{"tx": {...}, "mode": "block"}'
```

---

## 📊 Monitoring & Verification

### Node Health Check

```bash
# Check if node is running and synced
curl http://localhost:26657/status | jq '.result.sync_info.catching_up'
# Output: false (when synced)

# Get current block height
curl http://localhost:26657/status | jq '.result.sync_info.latest_block_height'

# Get peer count
curl http://localhost:26657/net_info | jq '.result.n_peers'
```

### Dashboard Monitoring

Start the Flask API and open the dashboard:

```bash
# Terminal 1: Start Flask API
cd backend
python app.py

# Terminal 2: Open dashboard in browser
http://localhost:5000/dashboard.html
```

The dashboard shows:
- Real-time block height
- Node sync status
- Transaction volume
- Anomaly detection metrics
- Validator information

### Logs Monitoring

```bash
# View last 100 lines of logs
tail -100 ~/.qieMainnetNode/qie.log

# Follow logs in real-time
tail -f ~/.qieMainnetNode/qie.log

# Search for errors
grep -i "error\|warn" ~/.qieMainnetNode/qie.log
```

---

## ⏭️ Next Steps

### 1. Get QIE Coins

Your validator needs QIE coins for staking. Get testnet coins from the faucet:

```bash
# Visit: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins

# Check balance
~/.qie/qied query bank balances <your_address> --home ~/.qieMainnetNode
```

### 2. Create Validator

Once you have QIE coins in your wallet, create a validator:

```bash
bash scripts/create_validator.sh
```

This will:
- Create a staking transaction
- Submit validator information
- Join the active validator set

### 3. Monitor Your Validator

```bash
# Query your validator
~/.qie/qied query staking validator <validator_address> --home ~/.qieMainnetNode

# View delegations
~/.qie/qied query staking delegations-to <validator_address> --home ~/.qieMainnetNode

# Check rewards
~/.qie/qied query distribution rewards <your_address> --home ~/.qieMainnetNode
```

---

## 🔧 Troubleshooting

### Node not syncing

```bash
# Check RPC connection
curl http://localhost:26657/status

# Check peers
curl http://localhost:26657/net_info

# Restart node
pkill -f "qied start"
sleep 5
bash scripts/start_qie_node.sh
```

### Wallet not found

```bash
# List all keys
~/.qie/qied keys list --home ~/.qieMainnetNode

# If empty, recreate:
bash scripts/create_wallet.sh
```

### RPC timeout errors

```bash
# Increase RPC timeout in config.toml
nano ~/.qieMainnetNode/config/config.toml

# Find: timeout_broadcast = "10s"
# Change to: timeout_broadcast = "30s"

# Restart node
pkill -f "qied start"
bash scripts/start_qie_node.sh
```

### Out of sync issues

```bash
# Check if node is still catching up
curl http://localhost:26657/status | jq '.result.sync_info'

# If catching_up is true, wait for sync to complete
# Check logs:
tail -f ~/.qieMainnetNode/qie.log | grep -i "committed"
```

---

## 📚 File Reference

### Scripts

| Script | Purpose | Duration |
|--------|---------|----------|
| `install_qie.sh` | Download and install QIE binary | < 1 min |
| `init_qie_node.sh` | Initialize node configuration | < 1 min |
| `configure_qie_node.sh` | Configure genesis, ports, moniker | < 1 min |
| `start_qie_node.sh` | Start node and wait for sync | 10-30 min |
| `create_wallet.sh` | Create validator wallet (keypair) | < 1 min |
| `run_validator_setup.sh` | Run all steps automatically | 15-40 min |
| `verify_qie_setup.sh` | Verify system and installation | < 1 min |

### Python Modules

| Module | Purpose |
|--------|---------|
| `qie_node_manager.py` | Node RPC communication and management |
| `qie_wallet_manager.py` | Wallet operations and queries |
| `test_qie_node_manager.py` | Unit tests for node manager |
| `app.py` | Flask REST API for all operations |

### Configuration Files

| File | Location |
|------|----------|
| Node home | `~/.qieMainnetNode` |
| Config | `~/.qieMainnetNode/config/config.toml` |
| Genesis | `~/.qieMainnetNode/config/genesis.json` |
| Validator key | `~/.qieMainnetNode/config/priv_validator_key.json` |
| Keyring | `~/.qieMainnetNode/keyring-test` |

---

## 🔐 Security Best Practices

1. **Backup Everything**
   - Backup `~/.qieMainnetNode` directory
   - Backup `~/.qie` directory
   - Store backups securely offline

2. **Protect Private Keys**
   - Never commit keys to git
   - Never share wallet passwords
   - Use hardware wallet for mainnet (if supported)

3. **Monitor Node Health**
   - Set up alerts for node downtime
   - Monitor disk space
   - Monitor memory and CPU usage

4. **Regular Updates**
   - Subscribe to QIE security announcements
   - Update QIE binary when new versions released
   - Apply system patches promptly

---

## 📞 Support & Resources

- **QIE Documentation**: https://docs.qie.digital
- **Validator Guide**: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3
- **Community**: Discord, Telegram (see QIE docs)

---

## 📝 Version History

- **v1.0.0** (2025-01-15): Initial release with complete validator setup
  - All 5 validator setup steps
  - Wallet management utilities
  - Flask API integration
  - Python module for programmatic access

---

**Last Updated**: January 15, 2025  
**Status**: Production Ready  
**License**: MIT
