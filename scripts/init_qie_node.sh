#!/usr/bin/env bash
set -euo pipefail

# init_qie_node.sh
# Initialize a QIE node with validator setup
# Reference: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/3.-initialize-your-node
#
# Usage:
#   bash scripts/init_qie_node.sh
#   QIE_MONIKER="my-validator" bash scripts/init_qie_node.sh

#########################################
# Configuration
QIE_MONIKER="${QIE_MONIKER:-valiguard-ai-validator}"
QIE_CHAIN_ID="${QIE_CHAIN_ID:-qie_1990-1}"
QIE_HOME="${QIE_HOME:-$HOME/.qieMainnetNode}"
QIED_BIN="${QIED_BIN:-$(command -v qied || echo /usr/local/bin/qied)}"

#########################################
# Helper functions
log()  { printf "[INFO] %s\n" "$*"; }
err()  { printf "[ERROR] %s\n" "$*" >&2; }
fatal(){ err "$*"; exit 1; }

#########################################
# 1) Validate prerequisites
log "Initializing QIE node: $QIE_MONIKER (chain: $QIE_CHAIN_ID)"

if [ ! -x "$QIED_BIN" ]; then
  # Try to find qied in common locations
  for candidate in /usr/local/bin/qied /usr/bin/qied "$HOME/qie-node/QIEV3Mainnet/qied"; do
    if [ -x "$candidate" ]; then
      QIED_BIN="$candidate"
      break
    fi
  done
fi

[ -x "$QIED_BIN" ] || fatal "qied binary not found. Please run install_qie.sh first or set QIED_BIN environment variable."

log "Using qied binary: $QIED_BIN"

#########################################
# 2) Initialize node directory structure
log "Initializing node configuration in: $QIE_HOME"
mkdir -p "$QIE_HOME"

# Check if already initialized
if [ -f "$QIE_HOME/config/config.toml" ]; then
  log "Node appears to already be initialized at $QIE_HOME"
  log "If you want to reinitialize, remove $QIE_HOME and re-run this script."
else
  # Initialize: this creates config/, data/, priv_validator_key.json, node_key.json
  "$QIED_BIN" init "$QIE_MONIKER" --chain-id "$QIE_CHAIN_ID" --home "$QIE_HOME" || fatal "Failed to initialize node"
  log "Node structure created"
fi

#########################################
# 3) Create validator keys (if not already present)
log "Setting up validator keys"

# The init command creates priv_validator_key.json, which is used for signing blocks/proposals
if [ ! -f "$QIE_HOME/config/priv_validator_key.json" ]; then
  err "priv_validator_key.json not found. Run init again or check $QIE_HOME/config"
else
  log "Validator key exists: $QIE_HOME/config/priv_validator_key.json"
fi

# Optional: Create/import account keys using 'qied keys add'
# This is typically done separately during validator setup
log "Validator keys are configured; use 'qied keys' to manage accounts"

#########################################
# 4) Verify initialization
log "Verifying node configuration"

if [ ! -f "$QIE_HOME/config/config.toml" ]; then
  fatal "config.toml not found after initialization"
fi

if [ ! -f "$QIE_HOME/config/app.toml" ]; then
  fatal "app.toml not found after initialization"
fi

if [ ! -d "$QIE_HOME/data" ]; then
  fatal "data directory not found after initialization"
fi

log "Node initialized successfully"
log "QIE_HOME: $QIE_HOME"
log "Chain ID: $QIE_CHAIN_ID"
log "Moniker: $QIE_MONIKER"

cat <<'EOF'

Next steps:
 1. Run the configure script to copy genesis and config files:
    bash scripts/configure_qie_node.sh

 2. Create and manage validator keys:
    qied keys add <key-name> --home "$QIE_HOME"

 3. Once configured, start the node:
    qied start --home "$QIE_HOME"

 4. Monitor node sync status and become a validator.

EOF

exit 0
