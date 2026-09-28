#!/bin/bash

##############################################################################
# create_wallet.sh
# Create QIE Validator Wallet (Keypair)
#
# This script creates a new wallet address for validator operations.
# Based on official QIE documentation:
# https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/6.-create-wallet-keypair
#
# Usage: bash scripts/create_wallet.sh [wallet_name]
# Default wallet_name: "validator"
##############################################################################

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
QIE_HOME="${HOME}/.qieMainnetNode"
QIE_BINARY="${HOME}/.qie/qied"
WALLET_NAME="${1:-validator}"
WALLET_PASSWORD_FILE="${QIE_HOME}/.wallet_password"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      QIE Validator Wallet Creation - Step 6               ║${NC}"
echo -e "${BLUE}║                                                            ║${NC}"
echo -e "${BLUE}║  This will create a new wallet for validator operations   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# 1. PRE-CHECKS
# ============================================================================
echo -e "${YELLOW}[STEP 1] Performing pre-checks...${NC}"

# Check if QIE binary exists
if [ ! -f "$QIE_BINARY" ]; then
    echo -e "${RED}✗ ERROR: QIE binary not found at $QIE_BINARY${NC}"
    echo -e "${YELLOW}Run: bash scripts/install_qie.sh${NC}"
    exit 1
fi
echo -e "${GREEN}✓ QIE binary found${NC}"

# Check if node directory exists
if [ ! -d "$QIE_HOME" ]; then
    echo -e "${RED}✗ ERROR: Node directory not found at $QIE_HOME${NC}"
    echo -e "${YELLOW}Run: bash scripts/setup_qie_validator.sh${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node directory exists${NC}"

# Check if node is running and synced
echo -e "${YELLOW}Checking if node is running and synced...${NC}"

if ! curl -s "http://localhost:26657/status" > /dev/null 2>&1; then
    echo -e "${RED}✗ ERROR: Node RPC not responding${NC}"
    echo -e "${YELLOW}Run: bash scripts/start_qie_node.sh${NC}"
    exit 1
fi

RESPONSE=$(curl -s "http://localhost:26657/status")
if ! echo "$RESPONSE" | grep -q '"catching_up":false'; then
    echo -e "${YELLOW}⚠ WARNING: Node is still syncing${NC}"
    echo -e "${YELLOW}Consider waiting for full sync before creating wallet${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

BLOCK_HEIGHT=$(echo "$RESPONSE" | grep -o '"latest_block_height":"[^"]*"' | cut -d'"' -f4)
echo -e "${GREEN}✓ Node is running (Block height: $BLOCK_HEIGHT)${NC}"

echo ""

# ============================================================================
# 2. CHECK FOR EXISTING WALLET
# ============================================================================
echo -e "${YELLOW}[STEP 2] Checking for existing wallet...${NC}"

# List existing keys
EXISTING_KEYS=$("$QIE_BINARY" keys list --home "$QIE_HOME" 2>/dev/null | grep "name:" || true)

if echo "$EXISTING_KEYS" | grep -q "$WALLET_NAME"; then
    echo -e "${YELLOW}⚠ WARNING: Wallet '$WALLET_NAME' already exists${NC}"
    echo -e "${BLUE}Existing wallets:${NC}"
    "$QIE_BINARY" keys list --home "$QIE_HOME" | grep -E "(name:|address:)" | sed 's/^/  /'
    echo ""
    read -p "Create new wallet anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cancelled wallet creation${NC}"
        exit 0
    fi
fi

echo -e "${GREEN}✓ Ready to create wallet${NC}"
echo ""

# ============================================================================
# 3. CREATE WALLET
# ============================================================================
echo -e "${YELLOW}[STEP 3] Creating wallet...${NC}"
echo -e "${BLUE}Wallet name: $WALLET_NAME${NC}"
echo -e "${BLUE}Wallet home: $QIE_HOME${NC}"
echo ""
echo -e "${CYAN}You will be prompted to set a password.${NC}"
echo -e "${CYAN}IMPORTANT: Save this password securely! You'll need it for signing transactions.${NC}"
echo ""

# Create the wallet interactively
"$QIE_BINARY" keys add "$WALLET_NAME" --home "$QIE_HOME"

echo ""
echo -e "${GREEN}✓ Wallet created successfully!${NC}"
echo ""

# ============================================================================
# 4. RETRIEVE WALLET DETAILS
# ============================================================================
echo -e "${YELLOW}[STEP 4] Retrieving wallet details...${NC}"
echo ""

# Get wallet details
WALLET_INFO=$("$QIE_BINARY" keys show "$WALLET_NAME" --home "$QIE_HOME")

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}WALLET DETAILS${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo "$WALLET_INFO" | sed 's/^/  /'
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Extract address and pubkey
WALLET_ADDRESS=$(echo "$WALLET_INFO" | grep "address:" | awk '{print $2}')
WALLET_PUBKEY=$(echo "$WALLET_INFO" | grep "pubkey:" | cut -d"'" -f2)

echo -e "${GREEN}✓ Wallet Address: ${CYAN}$WALLET_ADDRESS${NC}"
echo -e "${GREEN}✓ Public Key: ${CYAN}$WALLET_PUBKEY${NC}"
echo ""

# ============================================================================
# 5. SAVE WALLET INFO
# ============================================================================
echo -e "${YELLOW}[STEP 5] Saving wallet information...${NC}"

WALLET_INFO_FILE="${QIE_HOME}/wallet_info.txt"

cat > "$WALLET_INFO_FILE" << EOF
QIE Validator Wallet Information
Generated: $(date)

Wallet Name: $WALLET_NAME
Wallet Address: $WALLET_ADDRESS
Home Directory: $QIE_HOME

Full Details:
$WALLET_INFO

EOF

echo -e "${GREEN}✓ Wallet info saved to: $WALLET_INFO_FILE${NC}"
echo ""

# ============================================================================
# 6. NEXT STEPS
# ============================================================================
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                    ✓ WALLET CREATED!                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${CYAN}📋 IMPORTANT INFORMATION:${NC}"
echo ""
echo -e "  ${GREEN}Wallet Address:${NC} $WALLET_ADDRESS"
echo -e "  ${GREEN}Home Directory:${NC}  $QIE_HOME"
echo -e "  ${GREEN}Info File:${NC}       $WALLET_INFO_FILE"
echo ""

echo -e "${YELLOW}⏭️  NEXT STEPS:${NC}"
echo ""
echo -e "  ${CYAN}1. Get QIE Coins${NC}"
echo -e "     Visit: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins"
echo -e "     You need QIE coins for staking"
echo ""
echo -e "  ${CYAN}2. Create Validator${NC}"
echo -e "     Run: bash scripts/create_validator.sh"
echo -e "     (You'll need coins in your wallet first)"
echo ""
echo -e "  ${CYAN}3. Monitor Your Validator${NC}"
echo -e "     Query balance:  $QIE_BINARY query bank balances $WALLET_ADDRESS --home \"$QIE_HOME\""
echo -e "     Query validator: $QIE_BINARY query staking validators --home \"$QIE_HOME\""
echo ""

echo -e "${RED}🔒 SECURITY REMINDER:${NC}"
echo -e "  • Never share your wallet password"
echo -e "  • Keep your private keys secure"
echo -e "  • Back up your $QIE_HOME directory"
echo ""
