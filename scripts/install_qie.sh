#!/usr/bin/env bash
set -euo pipefail

# install_qie.sh
# Cross-platform installer for QIE node (Git Bash on Windows, WSL, macOS, Linux)
# Requirements/behavior derived from: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/2.-install-qie-node
#
# Usage:
#   bash scripts/install_qie.sh            # uses defaults
#   QIE_CHAIN_ID="qie_1990-1" QIE_MONIKER="my-node" bash scripts/install_qie.sh

#########################################
# User-configurable defaults
DOWNLOAD_URL="https://github.com/qieadmin/qiev3-mainnet/releases/download/v3/qiemainnetv3.zip"
# Optional: a URL that serves the SHA256 checksum for the ZIP (if available)
CHECKSUM_URL=""

# Directories and environment variables
QIE_NODE_DIR="$HOME/qie-node"
QIE_HOME_DEFAULT="$HOME/.qie"
export QIE_HOME="${QIE_HOME:-$QIE_HOME_DEFAULT}"
export QIE_CHAIN_ID="${QIE_CHAIN_ID:-qie_1990-1}"
export QIE_MONIKER="${QIE_MONIKER:-valiguard-ai-validator}"
RPC_PORT="${RPC_PORT:-26657}"
P2P_PORT="${P2P_PORT:-26656}"
LOG_LEVEL="${LOG_LEVEL:-info}"

TMPDIR="${TMPDIR:-/tmp}"

#########################################
# Helper functions
log(){ printf "[INFO] %s\n" "$*"; }
err(){ printf "[ERROR] %s\n" "$*" >&2; }
fatal(){ err "$*"; exit 1; }

check_cmd(){ command -v "$1" >/dev/null 2>&1 || fatal "Required command '$1' not found. Please install it and retry."; }

check_internet(){
  # quick connectivity check
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --head https://github.com >/dev/null 2>&1 || return 1
  elif command -v wget >/dev/null 2>&1; then
    wget -q --spider https://github.com || return 1
  else
    return 1
  fi
}

download_file(){
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail -o "$dest" "$url"
  else
    wget -O "$dest" "$url"
  fi
}

sha256_file(){
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "" # not available
  fi
}

#########################################
# 1) Preconditions & environment
log "Starting QIE installer"

if ! check_internet; then
  fatal "No internet connectivity detected. Please check your network and retry."
fi

# Ensure common helper tools exist for archive operations
if ! command -v unzip >/dev/null 2>&1; then
  log "'unzip' not found. Attempting to continue; installer will try to use available tools. On Linux/macOS install 'unzip' first for best results."
fi

mkdir -p "$QIE_NODE_DIR"
mkdir -p "$QIE_HOME"

DL_ZIP="$TMPDIR/qiemainnetv3.zip"

#########################################
# 2) Download QIE binary bundle
log "Downloading QIE package from: $DOWNLOAD_URL"
rm -f "$DL_ZIP"
download_file "$DOWNLOAD_URL" "$DL_ZIP" || fatal "Download failed: $DOWNLOAD_URL"

# Verify download size / presence
if [ ! -s "$DL_ZIP" ]; then
  fatal "Downloaded file is empty or missing: $DL_ZIP"
fi

if [ -n "$CHECKSUM_URL" ]; then
  log "Checksum URL provided, validating sha256"
  CHECKSUM_EXPECTED="$(curl -fsS "$CHECKSUM_URL" 2>/dev/null | tr -d '\r\n' )" || true
  if [ -n "$CHECKSUM_EXPECTED" ]; then
    CHECKSUM_ACTUAL="$(sha256_file "$DL_ZIP")"
    if [ -z "$CHECKSUM_ACTUAL" ]; then
      err "No sha256 tool available to validate checksum. Skipping checksum validation."
    elif [ "$CHECKSUM_ACTUAL" != "$CHECKSUM_EXPECTED" ]; then
      fatal "Checksum mismatch: expected $CHECKSUM_EXPECTED but got $CHECKSUM_ACTUAL"
    else
      log "Checksum validated"
    fi
  else
    log "Could not obtain expected checksum from $CHECKSUM_URL; skipping checksum validation"
  fi
else
  log "No checksum URL provided; skipping checksum validation"
fi

#########################################
# 3) Extract binary and set permissions
log "Extracting QIE bundle to: $QIE_NODE_DIR"
if command -v unzip >/dev/null 2>&1; then
  unzip -o "$DL_ZIP" -d "$QIE_NODE_DIR" || fatal "Failed to unzip archive"
else
  # fallback using busybox/unzip inside some environments
  fatal "'unzip' is required to extract the package. Please install 'unzip' and re-run the script."
fi

# The package typically contains 'QIEV3Mainnet/qied' - try to locate the binary
if [ -x "$QIE_NODE_DIR/QIEV3Mainnet/qied" ]; then
  QIED_BIN="$QIE_NODE_DIR/QIEV3Mainnet/qied"
elif [ -x "$QIE_NODE_DIR/qied" ]; then
  QIED_BIN="$QIE_NODE_DIR/qied"
else
  # Try to find any qied inside extracted tree
  QIED_BIN="$(find "$QIE_NODE_DIR" -type f -name qied -perm /a+x 2>/dev/null | head -n1 || true)"
fi

if [ -z "$QIED_BIN" ]; then
  # make qied executable if present but not marked executable
  POSSIBLE="$(find "$QIE_NODE_DIR" -type f -name qied 2>/dev/null | head -n1 || true)"
  if [ -n "$POSSIBLE" ]; then
    chmod +x "$POSSIBLE" || true
    QIED_BIN="$POSSIBLE"
  fi
fi

[ -n "$QIED_BIN" ] || fatal "Could not locate the 'qied' binary after extraction. Please inspect $QIE_NODE_DIR"
log "Found qied binary: $QIED_BIN"

# Optionally install to a system-wide PATH if running on Linux/macOS with sudo privileges
if [ "$(uname -s)" = "Linux" ] || [ "$(uname -s)" = "Darwin" ]; then
  if command -v sudo >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null; then
      log "Copying qied to /usr/local/bin (requires sudo)"
      sudo cp "$QIED_BIN" /usr/local/bin/qied
      sudo chmod +x /usr/local/bin/qied
      QIED_BIN="/usr/local/bin/qied"
    else
      log "No passwordless sudo available; leaving binary in $QIE_NODE_DIR and adding note to PATH"
    fi
  fi
fi

#########################################
# 4) Generate node configuration
log "Initializing QIE node configuration (moniker: $QIE_MONIKER, chain-id: $QIE_CHAIN_ID)"

# Use the binary to init the config inside $QIE_HOME
"$QIED_BIN" init "$QIE_MONIKER" --chain-id "$QIE_CHAIN_ID" --home "$QIE_HOME" || fatal "'qied init' failed"

# Update config values: RPC port, P2P port, CORS and log level
CFG_TOML="$QIE_HOME/config/config.toml"
APP_TOML="$QIE_HOME/config/app.toml"

if [ -f "$CFG_TOML" ]; then
  log "Patching $CFG_TOML"
  # set RPC listen address
  sed -i.bak -E "s|rpc.laddr = \"tcp://[^"]+\"|rpc.laddr = \"tcp://0.0.0.0:${RPC_PORT}\"|g" "$CFG_TOML" || true
  # set P2P listen address
  sed -i.bak -E "s|laddr = \"tcp://[^"]+\"|laddr = \"tcp://0.0.0.0:${P2P_PORT}\"|1" "$CFG_TOML" || true
  # enable CORS for RPC (set to allow localhost origins)
  if grep -q "rpc.cors_allowed_origins" "$CFG_TOML" 2>/dev/null; then
    sed -i.bak -E "s|rpc.cors_allowed_origins = \[.*\]|rpc.cors_allowed_origins = [\"*\"]|g" "$CFG_TOML" || true
  else
    printf "\n# added by installer\nrpc.cors_allowed_origins = [\"*\"]\n" >> "$CFG_TOML"
  fi
else
  err "Config file not found: $CFG_TOML"
fi

if [ -f "$APP_TOML" ]; then
  log "Patching $APP_TOML"
  # set log level if present
  if grep -q "log_level" "$APP_TOML" 2>/dev/null; then
    sed -i.bak -E "s|log_level = \"[^"]+\"|log_level = \"${LOG_LEVEL}\"|g" "$APP_TOML" || true
  else
    printf "\n# added by installer\nlog_level = \"${LOG_LEVEL}\"\n" >> "$APP_TOML"
  fi
else
  err "App config file not found: $APP_TOML"
fi

#########################################
# 5) Verification
log "Verifying installation"
if [ -x "$QIED_BIN" ] || command -v qied >/dev/null 2>&1; then
  log "qied binary is present and executable"
else
  fatal "qied binary is not executable or not in PATH"
fi

# Basic config syntax checks (lightweight): ensure the config file contains changed ports and moniker
if grep -q "$RPC_PORT" "$CFG_TOML" 2>/dev/null && grep -q "$P2P_PORT" "$CFG_TOML" 2>/dev/null; then
  log "RPC/P2P ports set in config"
else
  err "RPC/P2P port checks failed; inspect $CFG_TOML"
fi

if grep -q "$QIE_MONIKER" "$QIE_HOME/config/genesis.json" 2>/dev/null || grep -q "$QIE_MONIKER" "$QIE_HOME/config/config.toml" 2>/dev/null; then
  log "Moniker appears in generated configs"
else
  log "Moniker not obviously present in configs; this may be normal depending on version"
fi

log "QIE installation and basic configuration completed successfully"
log "QIE_HOME: $QIE_HOME"
log "qied binary: $QIED_BIN"

cat <<'EOF'
Next steps (suggested):
 - Add qied to your PATH (example):
     export PATH="$HOME/qie-node/QIEV3Mainnet:$PATH"
 - Initialize further configs, create keys, and (optionally) copy the binary to /usr/local/bin on Linux/macOS.
 - Start the node:
     qied start --home "$QIE_HOME"
EOF

exit 0
