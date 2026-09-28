#!/bin/bash
# fix_node_config.sh - Configure QIE node

cd ~/.qieMainnetNode/config

# Add peers
sed -i 's/persistent_peers = ""/persistent_peers = "8bdb3094dd67e9d47550e7f99f7c0e1dd2a7defd@65.109.28.219:26656,d5519e378247dfb61dfe90652d1fe3e2b3005a5b@65.109.68.190:26656"/g' config.toml

# Set gas prices
sed -i 's/minimum-gas-prices = ""/minimum-gas-prices = "10000000000aqie"/g' app.toml

echo "✅ Config updated"

# Start node
mkdir -p ~/.qieMainnetNode/logs
nohup ~/.qie/qied start --home ~/.qieMainnetNode > ~/.qieMainnetNode/logs/node.log 2>&1 &

sleep 3

if ps aux | grep -q "[q]ied"; then
    echo "✅ Node started successfully"
    echo "📊 Check status: curl -s http://localhost:26657/status | jq '.result.sync_info'"
else
    echo "❌ Node failed to start"
    echo "📋 Check logs: tail -f ~/.qieMainnetNode/logs/node.log"
fi
