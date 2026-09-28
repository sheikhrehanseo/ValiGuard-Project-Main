#!/usr/bin/env bash
set -euo pipefail

# configure_qie_node.sh
# Configure QIE node with genesis and other required config files
# Reference: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/4.-configure-your-node
#
# Usage:
#   bash scripts/configure_qie_node.sh

#########################################
# Configuration
QIE_HOME="${QIE_HOME:-$HOME/.qieMainnetNode}"
QIE_NODE_DIR="${QIE_NODE_DIR:-$HOME/qie-node}"
QIE_MONIKER="${QIE_MONIKER:-valiguard-ai-validator}"
RPC_PORT="${RPC_PORT:-26657}"
P2P_PORT="${P2P_PORT:-26656}"
EXTERNAL_ADDRESS="${EXTERNAL_ADDRESS:-}"

#########################################
# Helper functions
log()  { printf "[INFO] %s\n" "$*"; }
err()  { printf "[ERROR] %s\n" "$*" >&2; }
fatal(){ err "$*"; exit 1; }

#########################################
# 1) Validate prerequisites
log "Configuring QIE node at: $QIE_HOME"

[ -d "$QIE_HOME/config" ] || fatal "Node not initialized. Run init_qie_node.sh first."
[ -d "$QIE_NODE_DIR/QIEV3Mainnet" ] || fatal "QIE installation directory not found: $QIE_NODE_DIR/QIEV3Mainnet"

#########################################
# 2) Replace genesis and config files from the QIE release package
log "Step 1: Remove auto-generated config files"
rm -f "$QIE_HOME/config/genesis.json"
rm -f "$QIE_HOME/config/config.toml"
rm -f "$QIE_HOME/config/client.toml"
rm -f "$QIE_HOME/config/app.toml"
log "Removed old config files"

log "Step 2: Copy genesis and config files from QIE release package"
cp -v "$QIE_NODE_DIR/QIEV3Mainnet/genesis.json" "$QIE_HOME/config/" || fatal "Failed to copy genesis.json"
cp -v "$QIE_NODE_DIR/QIEV3Mainnet/config.toml" "$QIE_HOME/config/" || fatal "Failed to copy config.toml"
cp -v "$QIE_NODE_DIR/QIEV3Mainnet/client.toml" "$QIE_HOME/config/" || fatal "Failed to copy client.toml"
cp -v "$QIE_NODE_DIR/QIEV3Mainnet/app.toml" "$QIE_HOME/config/" || fatal "Failed to copy app.toml"
log "Config files copied successfully"

#########################################
# 3) Set moniker in config.toml
log "Step 3: Set validator moniker to: $QIE_MONIKER"
CFG_TOML="$QIE_HOME/config/config.toml"

if grep -q "moniker = " "$CFG_TOML"; then
  sed -i.bak "s/moniker = .*/moniker = \"$QIE_MONIKER\"/" "$CFG_TOML" || true
  log "Moniker updated in config.toml"
else
  err "Could not find moniker setting in $CFG_TOML; manual update may be needed"
fi

#########################################
# 4) Configure RPC and P2P ports
log "Step 4: Configure RPC and P2P ports"
log "  RPC Port: $RPC_PORT"
log "  P2P Port: $P2P_PORT"

# Update RPC listen address
if grep -q "rpc.laddr" "$CFG_TOML"; then
  sed -i.bak -E "s|rpc\.laddr = \"tcp://[0-9.:]+\"|rpc.laddr = \"tcp://0.0.0.0:${RPC_PORT}\"|" "$CFG_TOML" || true
  log "RPC listen address updated"
fi

# Update P2P listen address
if grep -q "^laddr = " "$CFG_TOML"; then
  sed -i.bak -E "s|laddr = \"tcp://[0-9.:]+\"|laddr = \"tcp://0.0.0.0:${P2P_PORT}\"|" "$CFG_TOML" || true
  log "P2P listen address updated"
fi

#########################################
# 5) Configure external address if provided
if [ -n "$EXTERNAL_ADDRESS" ]; then
  log "Step 5: Setting external address to: $EXTERNAL_ADDRESS"
  if grep -q "external_address = " "$CFG_TOML"; then
    sed -i.bak "s|external_address = .*|external_address = \"$EXTERNAL_ADDRESS:${P2P_PORT}\"|" "$CFG_TOML" || true
    log "External address configured"
  fi
else
  log "Step 5: No external address provided (use EXTERNAL_ADDRESS env var to set)"
fi

#########################################
# 6) Enable CORS for development (optional)
log "Step 6: Enable CORS for RPC (optional)"
if grep -q "rpc.cors_allowed_origins" "$CFG_TOML"; then
  sed -i.bak 's|rpc.cors_allowed_origins = .*|rpc.cors_allowed_origins = ["*"]|' "$CFG_TOML" || true
else
  echo 'rpc.cors_allowed_origins = ["*"]' >> "$CFG_TOML"
fi
log "CORS enabled for local development"

#########################################
# 7) Verify configuration
log "Step 7: Verifying configuration"

if [ ! -f "$QIE_HOME/config/genesis.json" ]; then
  fatal "genesis.json not found after configuration"
fi

if ! grep -q "moniker = \"$QIE_MONIKER\"" "$CFG_TOML"; then
  err "Warning: Moniker may not have been set correctly"
fi

log "Configuration completed successfully"

cat <<'EOF'

Next steps:
 1. (Optional) Edit $QIE_HOME/config/config.toml manually for advanced settings
 2. (Optional) Copy genesis.json from existing nodes if needed
 3. Start your node:
    qied start --home "$QIE_HOME"
 4. Monitor sync status at http://localhost:26657/status

EOF

exit 0
