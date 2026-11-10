#!/bin/bash
# scripts/get_qie_coins_helper.sh
# Helper script to check the funding address and balance for QIE Validator Setup

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

# 2. Check Balance
echo "📋 Step 2: Current Balance"
# Try json output first (cleaner)
~/.qie/qied query bank balances $ADDRESS --chain-id qie_1990-1 --node tcp://localhost:26657 --output text 2>&1
echo ""

# 3. Instructions
echo "============================================================"
echo "👇 HOW TO ADD COINS"
echo "============================================================"
echo "1. Fund the validator address: $ADDRESS"
echo "2. Run this helper again to check its balance."
echo "3. For dashboard access, connect your existing MetaMask wallet and sign the login message."
echo "Dashboard login uses a nonce signature and JWT; no private-key export is needed."
echo ""
echo "After adding coins, run this script again to check balance."
echo "Once you have 10,000+ QIE, run: bash scripts/complete_validator_registration.sh"
echo "============================================================"
