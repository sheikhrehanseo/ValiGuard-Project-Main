#!/bin/bash

##############################################################################
# run_validator_setup.sh
# Complete QIE Validator Setup Orchestrator
#
# This script runs all validator setup steps in sequence:
# 1. Install QIE binary
# 2. Initialize node configuration
# 3. Configure node (genesis, ports, etc)
# 4. Start node and wait for sync
# 5. Create validator wallet
#
# Usage: bash scripts/run_validator_setup.sh
##############################################################################

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Counter for completed steps
STEP_NUM=0
TOTAL_STEPS=5

print_header() {
    echo ""
    echo -e "${MAGENTA}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║  $1${NC}"
    echo -e "${MAGENTA}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    STEP_NUM=$((STEP_NUM + 1))
    echo -e "${BLUE}[$STEP_NUM/$TOTAL_STEPS]${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Main execution
print_header "QIE VALIDATOR SETUP - COMPLETE ORCHESTRATOR"

echo -e "${CYAN}This script will guide you through the complete validator setup process.${NC}"
echo -e "${CYAN}Ensure you have at least 60GB disk space and stable internet connection.${NC}"
echo ""

# Ask for confirmation
read -p "Continue with setup? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Setup cancelled${NC}"
    exit 0
fi

echo ""

# ============================================================================
# STEP 1: INSTALL QIE BINARY
# ============================================================================
print_step "Installing QIE Binary"

if [ ! -f "${HOME}/.qie/qied" ]; then
    echo "Running install_qie.sh..."
    if bash scripts/install_qie.sh; then
        print_success "QIE binary installed"
    else
        print_error "Failed to install QIE binary"
        exit 1
    fi
else
    print_success "QIE binary already installed"
fi

echo ""

# ============================================================================
# STEP 2: INITIALIZE NODE
# ============================================================================
print_step "Initializing Node Configuration"

if [ ! -d "${HOME}/.qieMainnetNode" ]; then
    echo "Running init_qie_node.sh..."
    if bash scripts/init_qie_node.sh; then
        print_success "Node initialized"
    else
        print_error "Failed to initialize node"
        exit 1
    fi
else
    print_warning "Node directory already exists"
    read -p "Reinitialize? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if bash scripts/init_qie_node.sh; then
            print_success "Node reinitialized"
        else
            print_error "Failed to reinitialize node"
            exit 1
        fi
    fi
fi

echo ""

# ============================================================================
# STEP 3: CONFIGURE NODE
# ============================================================================
print_step "Configuring Node (Genesis, Ports, etc)"

echo "Running configure_qie_node.sh..."
if bash scripts/configure_qie_node.sh; then
    print_success "Node configured"
else
    print_error "Failed to configure node"
    exit 1
fi

echo ""

# ============================================================================
# STEP 4: START NODE AND WAIT FOR SYNC
# ============================================================================
print_step "Starting Node and Waiting for Sync"

echo "Running start_qie_node.sh..."
echo -e "${CYAN}This may take 10-30 minutes depending on network speed...${NC}"
echo ""

if bash scripts/start_qie_node.sh; then
    print_success "Node started and synced"
else
    print_warning "Node sync timeout or error"
    echo -e "${YELLOW}The node may still be syncing in the background.${NC}"
    echo -e "${YELLOW}Check logs and retry wallet creation later.${NC}"
    exit 1
fi

echo ""

# ============================================================================
# STEP 5: CREATE WALLET
# ============================================================================
print_step "Creating Validator Wallet"

read -p "Enter wallet name (default: validator): " WALLET_NAME
WALLET_NAME="${WALLET_NAME:-validator}"

echo "Running create_wallet.sh..."
if bash scripts/create_wallet.sh "$WALLET_NAME"; then
    print_success "Wallet created"
else
    print_error "Failed to create wallet"
    exit 1
fi

echo ""

# ============================================================================
# COMPLETION
# ============================================================================
print_header "✓ VALIDATOR SETUP COMPLETE!"

echo -e "${CYAN}Your QIE validator node is now running and ready!${NC}"
echo ""

echo -e "${YELLOW}📋 SUMMARY:${NC}"
echo -e "  • QIE binary installed"
echo -e "  • Node initialized and configured"
echo -e "  • Node started and synced"
echo -e "  • Validator wallet created"
echo ""

echo -e "${YELLOW}⏭️  NEXT STEPS:${NC}"
echo ""
echo -e "  ${CYAN}1. Get QIE Coins from Testnet Faucet${NC}"
echo -e "     Visit: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins"
echo ""
echo -e "  ${CYAN}2. Create Validator from Stake${NC}"
echo -e "     Run: bash scripts/create_validator.sh"
echo ""
echo -e "  ${CYAN}3. Monitor your Node${NC}"
echo -e "     • View logs: tail -f ~/.qieMainnetNode/qie.log"
echo -e "     • Check status: curl http://localhost:26657/status"
echo -e "     • Query balance: qied query bank balances <your_address> --home ~/.qieMainnetNode"
echo ""

echo -e "${BLUE}📚 DOCUMENTATION:${NC}"
echo -e "  QIE Docs: https://docs.qie.digital"
echo -e "  Setup Guide: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3"
echo ""

echo -e "${GREEN}Happy validating! 🚀${NC}"
echo ""
