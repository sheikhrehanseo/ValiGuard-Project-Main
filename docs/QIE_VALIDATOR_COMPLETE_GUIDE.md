# QIE Validator Setup and Registration

Complete guide for QIE validator setup, registration, and verification.

## Quick Start

### 1. Setup QIE Node

```bash
# Activate virtual environment
cd "g:\ValiGuard AI\valiguard-ai"
.\venv\Scripts\Activate.ps1

# Run full node setup
python backend/qie_setup_manager.py setup
```

This will:
- ✅ Validate system requirements (CPU, RAM, disk)
- ✅ Download QIE binary
- ✅ Install and configure node
- ✅ Initialize genesis
- ✅ Setup directories and configuration

### 2. Register Validator

```bash
# Run full validator registration
python backend/qie_validator_manager.py full
```

This will:
- 🔑 Get validator public key
- 📄 Create validator.json configuration
- 🚀 Submit registration transaction
- ✅ Verify validator status

### 3. Verify Validator

```bash
# Check validator status
python backend/qie_validator_manager.py verify

# List all validators
python backend/qie_validator_manager.py list

# Check on explorer
python backend/qie_validator_manager.py explorer
```

---

## Detailed Setup

### System Requirements

- **CPU**: Minimum 2 cores (4+ recommended)
- **RAM**: Minimum 4 GB (8+ GB recommended)
- **Disk**: Minimum 100 GB free space
- **OS**: Linux, macOS, or Windows (WSL2)

### Setup Manager (`qie_setup_manager.py`)

#### Commands

```bash
# Validate system requirements
python backend/qie_setup_manager.py validate

# Download QIE binary
python backend/qie_setup_manager.py download

# Install node
python backend/qie_setup_manager.py install

# Create configuration
python backend/qie_setup_manager.py config

# Initialize genesis
python backend/qie_setup_manager.py genesis

# Full setup (all steps)
python backend/qie_setup_manager.py setup

# Check node status
python backend/qie_setup_manager.py status

# Check sync progress
python backend/qie_setup_manager.py sync

# Check network connectivity
python backend/qie_setup_manager.py network

# Check resource usage
python backend/qie_setup_manager.py resources

# Generate Docker files
python backend/qie_setup_manager.py docker

# Show documentation
python backend/qie_setup_manager.py docs
```

#### Custom Configuration

```bash
# Custom moniker
python backend/qie_setup_manager.py setup --moniker "my-validator"

# Custom home directory
python backend/qie_setup_manager.py setup --home "/custom/path"

# Force download (overwrite existing)
python backend/qie_setup_manager.py download --force
```

#### Python API

```python
from backend.qie_setup_manager import QIESetupManager, NodeConfig

# Create custom config
config = NodeConfig(
    moniker="my-validator",
    rpc_port=26657,
    p2p_port=26656,
    enable_cors=True
)

# Initialize manager
manager = QIESetupManager(config)

# Run full setup
success = manager.run_full_setup()

# Or run individual steps
manager.validate_system_requirements()
manager.download_qie_binary()
manager.install_qie_node()
manager.create_node_config()
manager.initialize_genesis()

# Check node status
status = manager.get_node_status()
sync_info = manager.check_sync_progress()
network_info = manager.check_network_connectivity()
resources = manager.get_resource_usage()
```

---

## Validator Registration

### Prerequisites

1. ✅ QIE node installed and running
2. ✅ Wallet created with QIE coins
3. ✅ Node fully synced with network

### Validator Manager (`qie_validator_manager.py`)

#### Commands

```bash
# Get validator public key
python backend/qie_validator_manager.py pubkey

# Create validator configuration
python backend/qie_validator_manager.py create-config

# Register validator
python backend/qie_validator_manager.py register

# Verify validator status
python backend/qie_validator_manager.py verify

# List all validators
python backend/qie_validator_manager.py list

# Check wallet balance
python backend/qie_validator_manager.py balance

# Open explorer link
python backend/qie_validator_manager.py explorer

# Show instructions
python backend/qie_validator_manager.py instructions

# Full registration process
python backend/qie_validator_manager.py full
```

#### Custom Configuration

```bash
# Custom moniker
python backend/qie_validator_manager.py full --moniker "my-validator"

# Custom wallet name
python backend/qie_validator_manager.py full --wallet "my-wallet"

# Custom staking amount (in aqie)
python backend/qie_validator_manager.py full --amount "20000000000000000000000aqie"
```

#### Python API

```python
from backend.qie_validator_manager import QIEValidatorManager, ValidatorConfig

# Create custom config
config = ValidatorConfig(
    moniker="valiguard-ai-validator",
    amount="10000000000000000000000aqie",  # 10,000 QIE
    website="https://github.com/sunnyshin8/ValiGuard-AI",
    details="ValiGuard AI - Cross-chain bridge monitoring",
    commission_rate="0.1",  # 10%
    commission_max_rate="0.2",  # 20%
    commission_max_change_rate="0.01"  # 1% per day
)

# Initialize manager
manager = QIEValidatorManager(config)

# Run full registration
success = manager.run_full_registration()

# Or run individual steps
pubkey = manager.get_validator_pubkey()
manager.create_validator_json()
manager.register_validator()
validator_info = manager.verify_validator()

# Check status
balance = manager.get_wallet_balance()
validators = manager.list_all_validators()
```

---

## Configuration Details

### Node Configuration

**File**: `~/.qieMainnetNode/config/config.toml`

Key settings:
- `moniker`: Validator name
- `rpc.laddr`: RPC endpoint (default: tcp://0.0.0.0:26657)
- `p2p.laddr`: P2P port (default: tcp://0.0.0.0:26656)
- `rpc.cors_allowed_origins`: CORS settings
- `log_level`: Logging level

### Validator Configuration

**File**: `~/.qieMainnetNode/validator.json`

```json
{
  "pubkey": {
    "@type": "/cosmos.crypto.ed25519.PubKey",
    "key": "LaUx9x1Nlj4t9Yy5ybFJR55/7kCK8eGn8JlY/mBewuU="
  },
  "amount": "10000000000000000000000aqie",
  "moniker": "valiguard-ai-validator",
  "identity": "",
  "website": "https://github.com/sunnyshin8/ValiGuard-AI",
  "security": "",
  "details": "ValiGuard AI - Cross-chain bridge monitoring",
  "commission-rate": "0.1",
  "commission-max-rate": "0.2",
  "commission-max-change-rate": "0.01",
  "min-self-delegation": "1000"
}
```

### Directories

- `~/.qie/` - QIE binary directory
  - `qied` - QIE daemon binary
- `~/.qieMainnetNode/` - Node home directory
  - `config/` - Configuration files
    - `config.toml` - Node configuration
    - `app.toml` - Application configuration
    - `genesis.json` - Genesis file
  - `data/` - Blockchain data
  - `logs/` - Log files

---

## Validator Registration Steps

### Step 1: Get Validator Public Key

```bash
# Using CLI
python backend/qie_validator_manager.py pubkey

# Or directly with qied
~/.qie/qied tendermint show-validator --home "$HOME/.qieMainnetNode"
```

Output:
```json
{
  "@type": "/cosmos.crypto.ed25519.PubKey",
  "key": "LaUx9x1Nlj4t9Yy5ybFJR55/7kCK8eGn8JlY/mBewuU="
}
```

### Step 2: Create Validator Configuration

```bash
# Using CLI
python backend/qie_validator_manager.py create-config

# This creates: ~/.qieMainnetNode/validator.json
```

### Step 3: Submit Registration Transaction

```bash
# Using CLI (interactive - prompts for password)
python backend/qie_validator_manager.py register

# Or directly with qied
~/.qie/qied tx staking create-validator ./validator.json \
  --from validator \
  --chain-id qie_1990-1 \
  --home "$HOME/.qieMainnetNode" \
  --node "tcp://localhost:26657" \
  --gas auto \
  --gas-adjustment 1.5 \
  --gas-prices 10000000000aqie
```

### Step 4: Verify Validator Status

```bash
# Using CLI
python backend/qie_validator_manager.py verify

# Or check all validators
python backend/qie_validator_manager.py list

# Or check on explorer
Visit: https://mainnet.qie.digital/validators
```

---

## Monitoring

### Node Status

```bash
# Check if node is running
python backend/qie_setup_manager.py status

# Check sync progress
python backend/qie_setup_manager.py sync

# Check network peers
python backend/qie_setup_manager.py network

# Check resource usage
python backend/qie_setup_manager.py resources
```

### Validator Status

```bash
# Check validator details
python backend/qie_validator_manager.py verify

# Check wallet balance
python backend/qie_validator_manager.py balance

# List all validators
python backend/qie_validator_manager.py list
```

---

## Docker Support

### Generate Docker Files

```bash
# Generate Dockerfile and docker-compose.yml
python backend/qie_setup_manager.py docker
```

### Run with Docker

```bash
# Build image
docker build -f Dockerfile.qie -t qie-node .

# Run with docker-compose
docker-compose -f docker-compose.qie.yml up -d

# Check logs
docker logs valiguard-ai-validator -f

# Stop node
docker-compose -f docker-compose.qie.yml down
```

---

## Troubleshooting

### Node Won't Start

```bash
# Check configuration syntax
python backend/qie_setup_manager.py config

# Reset node state
~/.qie/qied tendermint unsafe-reset-all --home "$HOME/.qieMainnetNode"

# Check logs
tail -f ~/.qieMainnetNode/logs/qied.log
```

### Validator Registration Failed

```bash
# Check wallet balance
python backend/qie_validator_manager.py balance

# Verify node is synced
python backend/qie_setup_manager.py sync

# Check validator pubkey
python backend/qie_validator_manager.py pubkey
```

### Cannot Find Validator

```bash
# Wait a few minutes after registration
# Then verify again
python backend/qie_validator_manager.py verify

# Check transaction status
~/.qie/qied query tx <TX_HASH> --chain-id qie_1990-1 --node "tcp://localhost:26657"
```

---

## Official Documentation

- **Main Guide**: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3
- **Install Node**: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/2.-install-qie-node
- **Get Coins**: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins
- **Register Validator**: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/8.-register-your-validator
- **Verify Validator**: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/9.-verify-your-validator

---

## Example Workflow

```bash
# 1. Activate venv
cd "g:\ValiGuard AI\valiguard-ai"
.\venv\Scripts\Activate.ps1

# 2. Setup node (one-time)
python backend/qie_setup_manager.py setup

# 3. Start node (in separate terminal)
~/.qie/qied start --home "$HOME/.qieMainnetNode"

# 4. Wait for sync to complete
python backend/qie_setup_manager.py sync

# 5. Create wallet (if not exists)
~/.qie/qied keys add validator --home "$HOME/.qieMainnetNode"

# 6. Get testnet coins
# Visit faucet: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins

# 7. Verify balance
python backend/qie_validator_manager.py balance

# 8. Register validator
python backend/qie_validator_manager.py full

# 9. Verify on-chain
python backend/qie_validator_manager.py verify

# 10. Check on explorer
python backend/qie_validator_manager.py explorer
```

---

## Commission Rates Explained

- **commission-rate**: Current commission (10% = 0.1)
  - Percentage of rewards you keep from delegators
  - Example: If delegators earn 100 QIE, you keep 10 QIE
  
- **commission-max-rate**: Maximum commission allowed (20% = 0.2)
  - You can never raise commission above this
  - Set conservatively for delegator trust
  
- **commission-max-change-rate**: Max daily change (1% = 0.01)
  - Maximum commission increase per day
  - Example: Can only increase from 10% to 11% per day

---

## Staking Amount

- **1 QIE** = 1,000,000,000,000,000,000 aqie (10^18)
- **Minimum stake**: 1,000 aqie
- **Recommended**: 10,000+ QIE for production validator

Examples:
```python
# 1 QIE
"1000000000000000000aqie"

# 100 QIE
"100000000000000000000aqie"

# 10,000 QIE (default)
"10000000000000000000000aqie"

# 1,000,000 QIE
"1000000000000000000000000aqie"
```

---

## Support

For issues or questions:
- GitHub: https://github.com/sunnyshin8/ValiGuard-AI
- QIE Docs: https://docs.qie.digital
