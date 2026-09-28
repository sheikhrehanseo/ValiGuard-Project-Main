#!/usr/bin/env bash
# complete_validator_registration.sh
# Complete validator registration for ValiGuard AI

set -e

echo "============================================================"
echo "🚀 ValiGuard AI - Complete Validator Registration"
echo "============================================================"
echo ""

# Step 1: Create validator wallet if it doesn't exist
echo "📋 Step 1: Checking for validator wallet..."
if ~/.qie/qied keys list --home ~/.qieMainnetNode 2>/dev/null | grep -q "validator"; then
    echo "✅ Validator wallet exists"
else
    echo "🔑 Creating validator wallet..."
    ~/.qie/qied keys add validator --home ~/.qieMainnetNode
    echo ""
    echo "⚠️  IMPORTANT: Save your mnemonic phrase securely!"
    echo "   You will need it to recover your wallet."
    echo ""
    read -p "Press Enter after saving your mnemonic..."
fi

# Get wallet address
echo ""
echo "📋 Step 2: Getting wallet address..."
WALLET_ADDRESS=$(~/.qie/qied keys show validator --home ~/.qieMainnetNode --output json 2>/dev/null | jq -r '.address')
echo "✅ Wallet address: $WALLET_ADDRESS"

# Step 3: Check if node is running
echo ""
echo "📋 Step 3: Checking if node is running..."
if curl -s http://localhost:26657/status >/dev/null 2>&1; then
    echo "✅ Node is running"
else
    echo "❌ Node is not running"
    echo ""
    echo "To start the node:"
    echo "   wsl bash -c '~/.qie/qied start --home ~/.qieMainnetNode > ~/.qieMainnetNode/logs/node.log 2>&1 &'"
    echo ""
    echo "Or start in foreground (new terminal):"
    echo "   wsl bash -c '~/.qie/qied start --home ~/.qieMainnetNode'"
    echo ""
    read -p "Press Enter after starting the node..."
fi

# Step 4: Check balance
echo ""
echo "📋 Step 4: Checking wallet balance..."
BALANCE_JSON=$(~/.qie/qied query bank balances $WALLET_ADDRESS --chain-id qie_1990-1 --node tcp://localhost:26657 --output json 2>/dev/null || echo '{"balances":[]}')
AQIE_BALANCE=$(echo $BALANCE_JSON | jq -r '.balances[] | select(.denom=="aqie") | .amount' || echo "0")

if [ "$AQIE_BALANCE" -eq "0" ] || [ -z "$AQIE_BALANCE" ]; then
    echo "❌ No QIE balance found"
    echo ""
    echo "📋 To get QIE coins:"
    echo "   1. Visit: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins"
    echo "   2. Send QIE to your wallet: $WALLET_ADDRESS"
    echo "   3. Wait for confirmation (check explorer: https://mainnet.qie.digital)"
    echo ""
    echo "Minimum required: 10,000 QIE"
    echo ""
    exit 1
else
    QIE_BALANCE=$(echo "scale=6; $AQIE_BALANCE / 1000000000000000000" | bc)
    echo "✅ Balance: $QIE_BALANCE QIE ($AQIE_BALANCE aqie)"
    
    # Check if sufficient
    MIN_BALANCE=10000000000000000000000
    if [ "$AQIE_BALANCE" -lt "$MIN_BALANCE" ]; then
        echo "⚠️  Low balance! Recommended: 10,000+ QIE for validator"
        echo ""
        read -p "Continue anyway? (yes/no): " CONTINUE
        if [ "$CONTINUE" != "yes" ]; then
            echo "❌ Registration cancelled"
            exit 1
        fi
    fi
fi

# Step 5: Get validator public key
echo ""
echo "📋 Step 5: Getting validator public key..."
PUBKEY=$(~/.qie/qied tendermint show-validator --home ~/.qieMainnetNode 2>/dev/null)
echo "✅ Validator public key:"
echo "$PUBKEY" | jq '.'

# Step 6: Create validator.json
echo ""
echo "📋 Step 6: Creating validator.json..."
cat > ~/.qieMainnetNode/validator.json <<EOF
{
  "pubkey": $PUBKEY,
  "amount": "10000000000000000000000aqie",
  "moniker": "valiguard-ai-validator",
  "identity": "",
  "website": "https://github.com/sunnyshin8/ValiGuard-AI",
  "security": "",
  "details": "ValiGuard AI - Cross-chain bridge monitoring and anomaly detection with ML-powered security",
  "commission-rate": "0.1",
  "commission-max-rate": "0.2",
  "commission-max-change-rate": "0.01",
  "min-self-delegation": "1000"
}
EOF

echo "✅ validator.json created"
echo ""
echo "📋 Validator Configuration:"
cat ~/.qieMainnetNode/validator.json | jq '.'

# Step 7: Register validator
echo ""
echo "============================================================"
echo "⚠️  VALIDATOR REGISTRATION"
echo "============================================================"
echo "This will stake 10,000 QIE from your validator wallet."
echo "You will be prompted for your wallet password."
echo "============================================================"
echo ""
read -p "🔐 Proceed with registration? (yes/no): " PROCEED

if [ "$PROCEED" != "yes" ]; then
    echo "❌ Registration cancelled"
    exit 1
fi

echo ""
echo "📡 Submitting create-validator transaction..."
~/.qie/qied tx staking create-validator ~/.qieMainnetNode/validator.json \
    --from validator \
    --chain-id qie_1990-1 \
    --home ~/.qieMainnetNode \
    --node tcp://localhost:26657 \
    --gas auto \
    --gas-adjustment 1.5 \
    --gas-prices 10000000000aqie \
    -y

echo ""
echo "✅ Transaction submitted!"
echo ""
echo "⏳ Waiting 10 seconds for confirmation..."
sleep 10

# Step 8: Verify validator
echo ""
echo "📋 Step 8: Verifying validator registration..."
VALIDATORS=$(~/.qie/qied query staking validators --chain-id qie_1990-1 --node tcp://localhost:26657 --output json 2>/dev/null || echo '{"validators":[]}')

if echo "$VALIDATORS" | jq -r '.validators[].description.moniker' | grep -q "valiguard"; then
    echo "✅ Validator found!"
    echo ""
    echo "$VALIDATORS" | jq -r '.validators[] | select(.description.moniker | contains("valiguard")) | {
        moniker: .description.moniker,
        operator_address: .operator_address,
        status: .status,
        jailed: .jailed,
        tokens: .tokens
    }'
else
    echo "⚠️  Validator not found in list yet"
    echo "   This is normal - may take a few minutes to appear"
    echo "   Total validators in network: $(echo "$VALIDATORS" | jq -r '.validators | length')"
fi

# Final instructions
echo ""
echo "============================================================"
echo "🎉 Validator Registration Complete!"
echo "============================================================"
echo ""
echo "📋 Next Steps:"
echo "   1. Wait 5-10 minutes for blockchain confirmation"
echo "   2. Verify status:"
echo "      wsl bash -c '~/.qie/qied query staking validator \$OPERATOR_ADDRESS --chain-id qie_1990-1 --node tcp://localhost:26657'"
echo "   3. Check on explorer: https://mainnet.qie.digital/validators"
echo "   4. Search for: valiguard-ai-validator"
echo ""
echo "📚 Documentation:"
echo "   See: docs/QIE_VALIDATOR_COMPLETE_GUIDE.md"
echo ""
echo "💡 Useful Commands:"
echo "   Check balance:  wsl bash -c '~/.qie/qied query bank balances $WALLET_ADDRESS --chain-id qie_1990-1 --node tcp://localhost:26657'"
echo "   Check status:  wsl bash -c '~/.qie/qied status --home ~/.qieMainnetNode'"
echo "   View logs:     wsl bash -c 'tail -f ~/.qieMainnetNode/logs/node.log'"
echo "============================================================"
echo ""
