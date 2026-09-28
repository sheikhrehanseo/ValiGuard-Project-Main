#!/usr/bin/env bash
set -euo pipefail

# verify_qie_setup.sh
# Verify that all QIE components are properly installed and configured
#
# Usage:
#   bash scripts/verify_qie_setup.sh

#########################################
# Configuration
QIE_HOME="${QIE_HOME:-$HOME/.qieMainnetNode}"
QIED_BIN="${QIED_BIN:-$(command -v qied || echo /usr/local/bin/qied)}"

#########################################
# Helper functions
log()  { printf "[✓] %s\n" "$*"; }
err()  { printf "[✗] %s\n" "$*" >&2; }
warn() { printf "[⚠] %s\n" "$*"; }
info() { printf "[ℹ] %s\n" "$*"; }

#########################################
# Checks
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNED=0

check_cmd() {
  local name="$1" cmd="${2:-$1}"
  if command -v "$cmd" >/dev/null 2>&1; then
    log "$name is installed"
    ((CHECKS_PASSED++))
  else
    err "$name is NOT installed"
    ((CHECKS_FAILED++))
  fi
}

check_file() {
  local name="$1" file="$2"
  if [ -f "$file" ]; then
    log "$name exists: $file"
    ((CHECKS_PASSED++))
  else
    err "$name NOT found: $file"
    ((CHECKS_FAILED++))
  fi
}

check_dir() {
  local name="$1" dir="$2"
  if [ -d "$dir" ]; then
    log "$name directory exists: $dir"
    ((CHECKS_PASSED++))
  else
    warn "$name directory NOT found: $dir (will be created on first run)"
    ((CHECKS_WARNED++))
  fi
}

check_executable() {
  local name="$1" file="$2"
  if [ -x "$file" ]; then
    log "$name is executable: $file"
    ((CHECKS_PASSED++))
  else
    err "$name is NOT executable: $file"
    ((CHECKS_FAILED++))
  fi
}

#########################################
# Start verification
echo "======================================"
echo "QIE Setup Verification"
echo "======================================"
echo ""

# 1. Check system requirements
echo "[1] System Requirements"
echo "---"
check_cmd "bash" "bash"
check_cmd "curl" "curl"
check_cmd "wget" "wget"
check_cmd "unzip" "unzip"
check_cmd "sed" "sed"
echo ""

# 2. Check Python environment
echo "[2] Python Environment"
echo "---"
if command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD=$(command -v python3 || command -v python)
  PYTHON_VER=$("$PYTHON_CMD" --version 2>&1 | awk '{print $2}')
  log "Python is available: $PYTHON_VER ($PYTHON_CMD)"
  ((CHECKS_PASSED++))
  
  # Check if requests module is available
  if "$PYTHON_CMD" -c "import requests" 2>/dev/null; then
    log "Python 'requests' module is available"
    ((CHECKS_PASSED++))
  else
    warn "Python 'requests' module NOT found (needed for qie_node_manager.py)"
    ((CHECKS_WARNED++))
  fi
  
  # Check if dotenv is available
  if "$PYTHON_CMD" -c "import dotenv" 2>/dev/null; then
    log "Python 'dotenv' module is available"
    ((CHECKS_PASSED++))
  else
    warn "Python 'dotenv' module NOT found"
    ((CHECKS_WARNED++))
  fi
else
  err "Python is NOT installed"
  ((CHECKS_FAILED++))
fi
echo ""

# 3. Check QIE installation
echo "[3] QIE Installation"
echo "---"
if [ -x "$QIED_BIN" ]; then
  QIED_VERSION=$("$QIED_BIN" version 2>/dev/null || echo "unknown")
  log "qied binary is installed: $QIED_BIN"
  ((CHECKS_PASSED++))
  info "Version: $QIED_VERSION"
else
  warn "qied binary NOT found at $QIED_BIN"
  info "Run: bash scripts/install_qie.sh"
  ((CHECKS_WARNED++))
fi
echo ""

# 4. Check node initialization
echo "[4] Node Configuration"
echo "---"
check_dir "QIE_HOME" "$QIE_HOME"
if [ -d "$QIE_HOME" ]; then
  check_dir "config" "$QIE_HOME/config"
  check_dir "data" "$QIE_HOME/data"
  check_file "config.toml" "$QIE_HOME/config/config.toml"
  check_file "app.toml" "$QIE_HOME/config/app.toml"
  check_file "genesis.json" "$QIE_HOME/config/genesis.json"
  check_file "priv_validator_key.json" "$QIE_HOME/config/priv_validator_key.json"
fi
echo ""

# 5. Check scripts
echo "[5] Setup Scripts"
echo "---"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check_file "install_qie.sh" "$SCRIPT_DIR/install_qie.sh"
check_executable "install_qie.sh" "$SCRIPT_DIR/install_qie.sh"
check_file "init_qie_node.sh" "$SCRIPT_DIR/init_qie_node.sh"
check_executable "init_qie_node.sh" "$SCRIPT_DIR/init_qie_node.sh"
check_file "configure_qie_node.sh" "$SCRIPT_DIR/configure_qie_node.sh"
check_executable "configure_qie_node.sh" "$SCRIPT_DIR/configure_qie_node.sh"
check_file "setup_qie_validator.sh" "$SCRIPT_DIR/setup_qie_validator.sh"
check_executable "setup_qie_validator.sh" "$SCRIPT_DIR/setup_qie_validator.sh"
echo ""

# 6. Check Python modules
echo "[6] Python Modules"
echo "---"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
check_file "qie_node_manager.py" "$PROJECT_ROOT/backend/qie_node_manager.py"
check_file "test_qie_node_manager.py" "$PROJECT_ROOT/backend/test_qie_node_manager.py"
echo ""

# 7. Check documentation
echo "[7] Documentation"
echo "---"
check_file "QIE_NODE_SETUP.md" "$PROJECT_ROOT/docs/QIE_NODE_SETUP.md"
check_file "QIE_QUICK_REFERENCE.md" "$PROJECT_ROOT/docs/QIE_QUICK_REFERENCE.md"
echo ""

# 8. Check node health (if running)
echo "[8] Node Status"
echo "---"
if curl -s http://localhost:26657/status >/dev/null 2>&1; then
  NODE_HEIGHT=$(curl -s http://localhost:26657/status | grep -o '"latest_block_height":"[^"]*' | cut -d'"' -f4 || echo "unknown")
  log "Node RPC endpoint is responding (height: $NODE_HEIGHT)"
  ((CHECKS_PASSED++))
else
  info "Node RPC endpoint not responding (node may not be running)"
  ((CHECKS_WARNED++))
fi
echo ""

# 9. Summary
echo "======================================"
echo "Verification Summary"
echo "======================================"
echo ""
echo "  Passed: $CHECKS_PASSED"
echo "  Failed: $CHECKS_FAILED"
echo "  Warned: $CHECKS_WARNED"
echo ""

if [ $CHECKS_FAILED -eq 0 ]; then
  if [ $CHECKS_WARNED -eq 0 ]; then
    echo "✓ All checks passed! Your QIE setup is ready."
    EXIT_CODE=0
  else
    echo "⚠ Setup is mostly ready, but some optional components are missing."
    echo "  See warnings above for details."
    EXIT_CODE=0
  fi
else
  echo "✗ Some checks failed. Please address the issues above."
  EXIT_CODE=1
fi

echo ""
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Review any failed or warning items above"
echo "2. Run: bash scripts/setup_qie_validator.sh"
echo "3. Start the node: qied start --home $QIE_HOME"
echo "4. Test the Python module: python backend/test_qie_node_manager.py"
echo ""

exit $EXIT_CODE
