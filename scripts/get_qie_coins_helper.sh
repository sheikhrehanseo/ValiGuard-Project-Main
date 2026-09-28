#!/bin/bash
# scripts/get_qie_coins_helper.sh
# Helper script to export key and check balance for QIE Validator Setup

echo "============================================================"
echo "💰 QIE Validator - Get Coins Helper"
echo "============================================================"
echo ""

# 1. Get Wallet Address
echo "📋 Step 1: Wallet Address"
ADDRESS=$(~/.qie/qied keys show validator --home ~/.qieMainnetNode --output json 2>/dev/null | grep "address" | cut -d '"' -f 4)
if [ -z "$ADDRESS" ]; then
    # Fallback if jq/json parsing fails or grep fails, try text output
    ADDRESS=$(~/.qie/qied keys show validator --home ~/.qieMainnetNode 2>&1 | grep "address:" | cut -d ':' -f 2 | tr -d ' ')
fi

if [ -z "$ADDRESS" ]; then
   # Hardcoded fallback from guide if detection fails
   ADDRESS="qie1ycctf3drjw6fzjpsdlxt6hh0muaasyhtl9ndld"
   echo "⚠️  Could not detect address automatically, using saved address:"
fi
echo "Address: $ADDRESS"
echo ""

# 2. Export Private Key
echo "📋 Step 2: Export Private Key (for MetaMask)"
echo "⚠️  WARNING: Do not share this key with anyone!"
echo "------------------------------------------------------------"
KEY=$(~/.qie/qied keys unsafe-export-eth-key validator --home ~/.qieMainnetNode 2>&1)
echo "$KEY"
echo "------------------------------------------------------------"
echo ""

# 3. Check Balance
echo "📋 Step 3: Current Balance"
# Try json output first (cleaner)
~/.qie/qied query bank balances $ADDRESS --chain-id qie_1990-1 --node tcp://localhost:26657 --output text 2>&1
echo ""

# 4. Instructions
echo "============================================================"
echo "👇 HOW TO ADD COINS"
echo "============================================================"
echo "1. Copy the Private Key above (inside the dashed lines)."
echo "2. Open MetaMask in your browser."
echo "3. Click the Account Icon (top right) -> 'Import Account'."
echo "4. Paste the Private Key and click 'Import'."
echo "5. You should see a new account. This is your Validator Wallet."
echo "6. Send 10,000+ QIE coins to this account address: $ADDRESS"
echo ""
echo "After adding coins, run this script again to check balance."
echo "Once you have 10,000+ QIE, run: bash scripts/complete_validator_registration.sh"
echo "============================================================"
