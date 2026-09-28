#!/bin/bash

##############################################################################
# start_qie_node.sh
# Start QIE Mainnet Node and Wait for Sync
#
# This script starts the QIE node using the configuration from setup.
# It uses screen to run the node in background (Linux/macOS).
# For Windows/Git Bash, modify to use appropriate terminal multiplexer.
#
# Usage: bash scripts/start_qie_node.sh
##############################################################################

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
QIE_HOME="${HOME}/.qieMainnetNode"
QIE_BINARY="${HOME}/.qie/qied"
RPC_PORT="26657"
MAX_WAIT_TIME=300  # 5 minutes timeout
CHECK_INTERVAL=5   # Check every 5 seconds

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         QIE Mainnet Node Starter - Step 5                 ║${NC}"
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
echo -e "${GREEN}✓ Node directory found${NC}"

# Check if config.toml exists
if [ ! -f "$QIE_HOME/config/config.toml" ]; then
    echo -e "${RED}✗ ERROR: config.toml not found${NC}"
    echo -e "${YELLOW}Run: bash scripts/configure_qie_node.sh${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Configuration file found${NC}"

echo ""

# ============================================================================
# 2. DETECT ENVIRONMENT
# ============================================================================
echo -e "${YELLOW}[STEP 2] Detecting environment...${NC}"

OS_TYPE="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS_TYPE="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS_TYPE="macos"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    OS_TYPE="windows"
fi

echo -e "${GREEN}✓ Detected OS: $OS_TYPE${NC}"
echo ""

# ============================================================================
# 3. CLEAN UP OLD PROCESSES (Optional)
# ============================================================================
echo -e "${YELLOW}[STEP 3] Checking for existing processes...${NC}"

# Kill any existing qied processes (optional - comment out if you want to keep running)
if pgrep -x "qied" > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠ Found existing qied process. Stopping it...${NC}"
    pkill -f "qied start" || true
    sleep 2
    echo -e "${GREEN}✓ Old process stopped${NC}"
else
    echo -e "${GREEN}✓ No existing processes${NC}"
fi

echo ""

# ============================================================================
# 4. START NODE
# ============================================================================
echo -e "${YELLOW}[STEP 4] Starting QIE Node...${NC}"
echo -e "${BLUE}Command: $QIE_BINARY start --home \"$QIE_HOME\"${NC}"
echo ""

# Start the node based on OS type
if [ "$OS_TYPE" = "windows" ]; then
    # For Windows/Git Bash - start in background with output to file
    echo -e "${YELLOW}Starting in background (Windows)...${NC}"
    nohup "$QIE_BINARY" start --home "$QIE_HOME" > "$QIE_HOME/qie.log" 2>&1 &
    NODE_PID=$!
    echo -e "${GREEN}✓ Node started with PID: $NODE_PID${NC}"
    echo -e "${GREEN}✓ Log file: $QIE_HOME/qie.log${NC}"
else
    # For Linux/macOS - start in screen session
    if ! command -v screen &> /dev/null; then
        echo -e "${YELLOW}⚠ 'screen' not found. Installing...${NC}"
        if [ "$OS_TYPE" = "linux" ]; then
            sudo apt-get update && sudo apt-get install -y screen
        elif [ "$OS_TYPE" = "macos" ]; then
            echo -e "${RED}Please install 'screen' manually: brew install screen${NC}"
            exit 1
        fi
    fi
    
    # Create/reattach to screen session
    SCREEN_NAME="qie-node"
    
    # Kill existing session if present
    screen -S "$SCREEN_NAME" -X quit 2>/dev/null || true
    sleep 1
    
    # Start new screen session with node
    screen -dmS "$SCREEN_NAME" -c /dev/null bash -c "$QIE_BINARY start --home \"$QIE_HOME\""
    
    sleep 2
    
    if screen -list | grep -q "$SCREEN_NAME"; then
        echo -e "${GREEN}✓ Node started in screen session: $SCREEN_NAME${NC}"
        echo -e "${BLUE}To view logs: screen -r $SCREEN_NAME${NC}"
        echo -e "${BLUE}To detach: Press Ctrl+A then D${NC}"
    else
        echo -e "${RED}✗ Failed to start screen session${NC}"
        exit 1
    fi
fi

echo ""

# ============================================================================
# 5. WAIT FOR SYNC
# ============================================================================
echo -e "${YELLOW}[STEP 5] Waiting for node to sync...${NC}"
echo -e "${BLUE}Checking RPC endpoint: http://localhost:$RPC_PORT/status${NC}"
echo ""

ELAPSED=0
SYNCED=false

while [ $ELAPSED -lt $MAX_WAIT_TIME ]; do
    if curl -s "http://localhost:$RPC_PORT/status" > /dev/null 2>&1; then
        RESPONSE=$(curl -s "http://localhost:$RPC_PORT/status")
        
        # Check if catching_up is false (node is synced)
        if echo "$RESPONSE" | grep -q '"catching_up":false'; then
            BLOCK_HEIGHT=$(echo "$RESPONSE" | grep -o '"latest_block_height":"[^"]*"' | cut -d'"' -f4)
            echo -e "${GREEN}✓ Node is SYNCED!${NC}"
            echo -e "${GREEN}✓ Latest block height: $BLOCK_HEIGHT${NC}"
            SYNCED=true
            break
        else
            # Still catching up - show current status
            BLOCK_HEIGHT=$(echo "$RESPONSE" | grep -o '"latest_block_height":"[^"]*"' | cut -d'"' -f4)
            echo -ne "${YELLOW}Syncing... Block height: $BLOCK_HEIGHT (Elapsed: ${ELAPSED}s)\r${NC}"
        fi
    else
        echo -ne "${YELLOW}Waiting for node to respond... (Elapsed: ${ELAPSED}s)\r${NC}"
    fi
    
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))
done

echo ""
echo ""

if [ "$SYNCED" = true ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                 ✓ NODE SYNC COMPLETE!                      ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Node is ready for wallet creation!${NC}"
    echo -e "${BLUE}Next step: bash scripts/create_wallet.sh${NC}"
    exit 0
else
    echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║           ✗ TIMEOUT WAITING FOR SYNC                       ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Node may still be syncing. Check logs:${NC}"
    if [ "$OS_TYPE" = "windows" ]; then
        echo -e "${YELLOW}tail -f $QIE_HOME/qie.log${NC}"
    else
        echo -e "${YELLOW}screen -r qie-node${NC}"
    fi
    exit 1
fi
