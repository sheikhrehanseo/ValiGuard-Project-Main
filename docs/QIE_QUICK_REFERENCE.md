# QIE Node Manager - Quick Reference

## One-Liner Setup

```bash
bash scripts/setup_qie_validator.sh
```

## Individual Scripts

| Script | Purpose | Time |
|--------|---------|------|
| `install_qie.sh` | Download & install QIE binary (~72 MB) | 1-2 min |
| `init_qie_node.sh` | Create node config & keys | <1 min |
| `configure_qie_node.sh` | Apply genesis & finalize config | <1 min |
| `setup_qie_validator.sh` | Run all three above | 2-3 min |

## Python Module Quick Start

```python
from qie_node_manager import QIENodeManager

m = QIENodeManager()                    # Use env vars or defaults
m.start_qie_node()                      # Start node
m.check_node_health()                   # Check status
m.wait_for_sync()                       # Wait to sync
m.get_latest_block()                    # Get current block
m.query_balance("qie1...")              # Query balance
m.broadcast_transaction(tx_dict)        # Send transaction
m.stop_qie_node()                       # Stop node
```

## Environment Setup

```bash
export QIE_MONIKER="my-validator"
export QIE_CHAIN_ID="qie_1990-1"
export QIE_HOME="$HOME/.qieMainnetNode"
export QIE_RPC_URL="http://localhost:26657"
```

## Key Files

| Path | Purpose |
|------|---------|
| `~/.qieMainnetNode/config/config.toml` | Node config (moniker, ports, etc.) |
| `~/.qieMainnetNode/config/app.toml` | App config (gas, log level, etc.) |
| `~/.qieMainnetNode/config/priv_validator_key.json` | **PRIVATE** - Validator signing key |
| `~/.qieMainnetNode/config/genesis.json` | Chain genesis block |

## Port Configuration

| Port | Service | Default |
|------|---------|---------|
| 26657 | RPC | ✓ |
| 26656 | P2P | ✓ |
| 26660 | Prometheus | (optional) |

## Common Commands

```bash
# Start node
qied start --home ~/.qieMainnetNode

# Check status
curl http://localhost:26657/status | jq .

# View logs
tail -f ~/.qieMainnetNode/log

# Create key
qied keys add <key-name> --home ~/.qieMainnetNode

# List keys
qied keys list --home ~/.qieMainnetNode

# Query balance
qied query bank balances <address> --home ~/.qieMainnetNode

# Get validator pubkey (for staking)
qied tendermint show-validator --home ~/.qieMainnetNode

# Become validator
qied tx staking create-validator \
  --moniker="<name>" \
  --amount=1000000aqie \
  --pubkey=$(qied tendermint show-validator) \
  --from=<key-name> \
  --home ~/.qieMainnetNode \
  --chain-id qie_1990-1
```

## Python Testing

```bash
cd backend
python test_qie_node_manager.py
```

## Debugging

```bash
# Check if qied binary exists
which qied

# Check node process
ps aux | grep qied

# Check port availability
lsof -i :26657

# Inspect config
cat ~/.qieMainnetNode/config/config.toml | grep -E "(moniker|rpc.laddr|laddr)"

# Reset node (WARNING: loses data)
qied tendermint unsafe-reset-all --home ~/.qieMainnetNode
```

## Log Levels

```bash
# Set in app.toml or via CLI
qied start --home ~/.qieMainnetNode --log_level=info   # info, debug, warn, error
```

## Default Values

```
QIE_HOME:       ~/.qieMainnetNode
QIE_CHAIN_ID:   qie_1990-1
QIE_MONIKER:    valiguard-ai-validator
QIE_RPC_URL:    http://localhost:26657
RPC_PORT:       26657
P2P_PORT:       26656
LOG_LEVEL:      info
```

## Security Tips

1. **Backup keys:**
   ```bash
   cp -r ~/.qieMainnetNode/config/priv_validator_key.json ~/secure_backup/
   ```

2. **Protect private validator key:**
   ```bash
   chmod 600 ~/.qieMainnetNode/config/priv_validator_key.json
   ```

3. **Use environment-specific configs:**
   ```bash
   # Testnet
   QIE_CHAIN_ID="qie-testnet" QIE_HOME="~/.qie-testnet" bash scripts/setup_qie_validator.sh
   
   # Mainnet
   QIE_CHAIN_ID="qie_1990-1" QIE_HOME="~/.qieMainnetNode" bash scripts/setup_qie_validator.sh
   ```

4. **Monitor node health:**
   ```bash
   while true; do
     curl -s http://localhost:26657/status | jq '.result.sync_info.catching_up'
     sleep 10
   done
   ```

## Useful Links

- [QIE Docs](https://docs.qie.digital)
- [Validator Guide](https://docs.qie.digital/how-to-become-a-validator-on-qie-v3)
- [Tendermint RPC](https://docs.tendermint.com/v0.38/rpc/)

---

**Last updated:** December 4, 2025
**Python module:** Python 3.10+
**OS Support:** Linux, macOS, Windows (WSL2/Git Bash)

