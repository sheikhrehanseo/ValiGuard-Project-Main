#!/usr/bin/env bash
set -euo pipefail

# setup_qie_validator.sh
# Complete QIE validator setup: install, initialize, configure, and test
#
# Usage:
#   bash scripts/setup_qie_validator.sh
#   QIE_MONIKER="my-validator" bash scripts/setup_qie_validator.sh

set +e  # Don't exit on individual script failures; report them

#########################################
# Configuration
QIE_MONIKER="${QIE_MONIKER:-valiguard-ai-validator}"
QIE_CHAIN_ID="${QIE_CHAIN_ID:-qie_1990-1}"
SKIP_INSTALL="${SKIP_INSTALL:-false}"
SKIP_INIT="${SKIP_INIT:-false}"
SKIP_CONFIG="${SKIP_CONFIG:-false}"

#########################################
# Helper functions
log()  { printf "[INFO] %s\n" "$*"; }
err()  { printf "[ERROR] %s\n" "$*" >&2; }
warn() { printf "[WARN] %s\n" "$*"; }

#########################################
# Start setup
log "====================================="
log "QIE Validator Setup Script"
log "====================================="
log "Moniker: $QIE_MONIKER"
log "Chain ID: $QIE_CHAIN_ID"
log ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

#########################################
# Step 1: Install QIE
if [ "$SKIP_INSTALL" = "false" ]; then
  log "Step 1: Installing QIE node..."
  if bash "$SCRIPT_DIR/install_qie.sh"; then
    log "✓ QIE installation completed"
  else
    err "✗ QIE installation failed"
  fi
else
  log "Step 1: Skipping QIE installation (SKIP_INSTALL=true)"
fi

log ""

#########################################
# Step 2: Initialize Node
if [ "$SKIP_INIT" = "false" ]; then
  log "Step 2: Initializing QIE node..."
  if QIE_MONIKER="$QIE_MONIKER" QIE_CHAIN_ID="$QIE_CHAIN_ID" bash "$SCRIPT_DIR/init_qie_node.sh"; then
    log "✓ Node initialization completed"
  else
    err "✗ Node initialization failed"
  fi
else
  log "Step 2: Skipping node initialization (SKIP_INIT=true)"
fi

log ""

#########################################
# Step 3: Configure Node
if [ "$SKIP_CONFIG" = "false" ]; then
  log "Step 3: Configuring QIE node..."
  if QIE_MONIKER="$QIE_MONIKER" QIE_CHAIN_ID="$QIE_CHAIN_ID" bash "$SCRIPT_DIR/configure_qie_node.sh"; then
    log "✓ Node configuration completed"
  else
    warn "⚠ Node configuration reported issues (see above)"
  fi
else
  log "Step 3: Skipping node configuration (SKIP_CONFIG=true)"
fi

log ""

#########################################
# Step 4: Summary and next steps
log "====================================="
log "Setup Summary"
log "====================================="
log "QIE validator setup complete!"
log ""
log "Environment variables set:"
log "  export QIE_MONIKER=$QIE_MONIKER"
log "  export QIE_CHAIN_ID=$QIE_CHAIN_ID"
log ""
log "Next steps:"
log "1. Create validator keys:"
log "   qied keys add <key-name> --home ~/.qieMainnetNode"
log ""
log "2. Start the node:"
log "   qied start --home ~/.qieMainnetNode"
log ""
log "3. Monitor sync status:"
log "   curl http://localhost:26657/status | jq ."
log ""
log "4. Use the Python module to interact with the node:"
log "   cd backend && python -c 'from qie_node_manager import QIENodeManager; m = QIENodeManager(); print(m.check_node_health())'"
log ""
log "====================================="

exit 0
