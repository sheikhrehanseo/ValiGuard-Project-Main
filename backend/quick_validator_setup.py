#!/usr/bin/env python3
"""
quick_validator_setup.py
Quick setup script to register ValiGuard AI as QIE validator

This script will:
1. Check if QIE is installed (if not, guide to install)
2. Check if wallet exists (if not, create one)
3. Check wallet balance (if low, guide to get coins)
4. Get validator public key
5. Create validator.json
6. Register validator
7. Verify registration
"""

import os
import sys
import json
import subprocess
from pathlib import Path

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_status(msg, status='info'):
    """Print colored status message"""
    colors = {'info': BLUE, 'success': GREEN, 'error': RED, 'warning': YELLOW}
    color = colors.get(status, RESET)
    print(f"{color}{msg}{RESET}")

def run_command(cmd, shell=True, check=False):
    """Run command and return output"""
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result
    except Exception as e:
        print_status(f"❌ Command failed: {e}", 'error')
        return None

def check_qie_installation():
    """Check if QIE is installed"""
    print_status("\n🔍 Checking QIE installation...", 'info')
    
    # Check in WSL
    result = run_command('wsl bash -c "ls ~/.qie/qied 2>&1"')
    if result and 'No such file' not in result.stdout:
        print_status("✅ QIE binary found in WSL", 'success')
        return 'wsl', 'wsl bash -c'
    
    # Check in Windows
    qied_path = os.path.expanduser('~/.qie/qied')
    if os.path.exists(qied_path):
        print_status("✅ QIE binary found in Windows", 'success')
        return 'windows', ''
    
    print_status("❌ QIE not installed", 'error')
    print_status("\n📋 To install QIE:", 'warning')
    print_status("   Option 1 (WSL - Recommended):", 'info')
    print_status('   wsl bash scripts/install_qie.sh', 'info')
    print_status("\n   Option 2 (Manual):", 'info')
    print_status('   1. Download: https://github.com/qieadmin/qiev3-mainnet/releases/download/v3/qiemainnetv3.zip', 'info')
    print_status('   2. Extract to ~/.qie/', 'info')
    print_status('   3. Run: bash scripts/init_qie_node.sh', 'info')
    
    return None, None

def check_wallet():
    """Check if wallet exists"""
    print_status("\n💰 Checking wallet...", 'info')
    
    # Try WSL
    result = run_command('wsl bash -c "~/.qie/qied keys list --home ~/.qieMainnetNode --output json 2>&1"')
    
    if result and result.returncode == 0:
        try:
            wallets = json.loads(result.stdout)
            if wallets:
                print_status(f"✅ Found {len(wallets)} wallet(s)", 'success')
                for wallet in wallets:
                    print_status(f"   - {wallet.get('name')}: {wallet.get('address')}", 'info')
                return True, wallets
        except:
            pass
    
    print_status("❌ No wallet found", 'error')
    print_status("\n📋 To create wallet:", 'warning')
    print_status('   wsl bash scripts/create_wallet.sh', 'info')
    print_status('   Or: wsl bash -c "~/.qie/qied keys add validator --home ~/.qieMainnetNode"', 'info')
    
    return False, []

def get_wallet_balance(wallet_address):
    """Get wallet balance"""
    print_status(f"\n💵 Checking balance for {wallet_address}...", 'info')
    
    cmd = f'wsl bash -c "~/.qie/qied query bank balances {wallet_address} --chain-id qie_1990-1 --node tcp://localhost:26657 --output json 2>&1"'
    result = run_command(cmd)
    
    if result and result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            balances = data.get('balances', [])
            
            for balance in balances:
                if balance.get('denom') == 'aqie':
                    aqie_amount = int(balance.get('amount', 0))
                    qie_amount = aqie_amount / (10**18)
                    print_status(f"✅ Balance: {qie_amount:.6f} QIE ({aqie_amount} aqie)", 'success')
                    
                    if qie_amount < 10000:
                        print_status("⚠️  Low balance! Need at least 10,000 QIE for validator", 'warning')
                        print_status("\n📋 Get QIE coins:", 'warning')
                        print_status('   Visit: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins', 'info')
                        return False
                    
                    return True
            
            print_status("❌ No aqie balance found", 'error')
            return False
            
        except Exception as e:
            print_status(f"❌ Failed to parse balance: {e}", 'error')
            return False
    
    print_status("❌ Could not check balance (node may not be running)", 'error')
    return False

def get_validator_pubkey():
    """Get validator public key"""
    print_status("\n🔑 Getting validator public key...", 'info')
    
    cmd = 'wsl bash -c "~/.qie/qied tendermint show-validator --home ~/.qieMainnetNode 2>&1"'
    result = run_command(cmd)
    
    if result and result.returncode == 0:
        try:
            pubkey = json.loads(result.stdout)
            print_status("✅ Validator public key retrieved", 'success')
            print_status(f"   Type: {pubkey.get('@type')}", 'info')
            print_status(f"   Key:  {pubkey.get('key')}", 'info')
            return pubkey
        except Exception as e:
            print_status(f"❌ Failed to parse public key: {e}", 'error')
            return None
    
    print_status("❌ Could not get validator public key", 'error')
    return None

def create_validator_json(pubkey):
    """Create validator.json file"""
    print_status("\n📄 Creating validator.json...", 'info')
    
    validator_config = {
        "pubkey": pubkey,
        "amount": "10000000000000000000000aqie",  # 10,000 QIE
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
    
    # Save to temp file in WSL
    validator_json = json.dumps(validator_config, indent=2)
    
    # Write to WSL filesystem
    cmd = f'wsl bash -c "cat > ~/.qieMainnetNode/validator.json << \'EOF\'\n{validator_json}\nEOF"'
    result = run_command(cmd)
    
    if result and result.returncode == 0:
        print_status("✅ validator.json created", 'success')
        print_status(f"\n📋 Validator Configuration:", 'info')
        print_status(f"   Moniker:         {validator_config['moniker']}", 'info')
        print_status(f"   Staking Amount:  {validator_config['amount']}", 'info')
        print_status(f"   Commission:      {validator_config['commission-rate']} (10%)", 'info')
        print_status(f"   Website:         {validator_config['website']}", 'info')
        return True
    
    print_status("❌ Failed to create validator.json", 'error')
    return False

def register_validator():
    """Register validator on-chain"""
    print_status("\n🚀 Registering validator...", 'info')
    
    print_status("\n" + "="*60, 'warning')
    print_status("⚠️  VALIDATOR REGISTRATION", 'warning')
    print_status("="*60, 'warning')
    print_status("This will stake 10,000 QIE from your validator wallet.", 'warning')
    print_status("You will be prompted for your wallet password.", 'warning')
    print_status("="*60 + "\n", 'warning')
    
    confirm = input("🔐 Proceed with registration? (yes/no): ")
    if confirm.lower() != 'yes':
        print_status("❌ Registration cancelled", 'error')
        return False
    
    cmd = '''wsl bash -c "~/.qie/qied tx staking create-validator ~/.qieMainnetNode/validator.json --from validator --chain-id qie_1990-1 --home ~/.qieMainnetNode --node tcp://localhost:26657 --gas auto --gas-adjustment 1.5 --gas-prices 10000000000aqie -y"'''
    
    print_status("\n📡 Submitting transaction...", 'info')
    result = run_command(cmd)
    
    if result:
        print_status("\n✅ Transaction submitted!", 'success')
        print_status(f"\nOutput:\n{result.stdout}", 'info')
        
        if result.stderr:
            print_status(f"\nErrors:\n{result.stderr}", 'warning')
        
        return True
    
    print_status("❌ Registration failed", 'error')
    return False

def verify_validator():
    """Verify validator registration"""
    print_status("\n✅ Verifying validator...", 'info')
    
    # Wait a moment for blockchain to process
    import time
    print_status("⏳ Waiting 10 seconds for transaction to confirm...", 'info')
    time.sleep(10)
    
    cmd = 'wsl bash -c "~/.qie/qied query staking validators --chain-id qie_1990-1 --node tcp://localhost:26657 --output json 2>&1"'
    result = run_command(cmd)
    
    if result and result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            validators = data.get('validators', [])
            
            # Find our validator
            for val in validators:
                moniker = val.get('description', {}).get('moniker', '')
                if 'valiguard' in moniker.lower():
                    print_status(f"✅ Validator found: {moniker}", 'success')
                    print_status(f"   Operator: {val.get('operator_address')}", 'info')
                    print_status(f"   Status:   {val.get('status')}", 'info')
                    print_status(f"   Jailed:   {val.get('jailed')}", 'info')
                    print_status(f"   Tokens:   {val.get('tokens')}", 'info')
                    return True
            
            print_status("⚠️  Validator not found yet", 'warning')
            print_status("   This is normal - may take a few minutes", 'info')
            print_status(f"   Total validators: {len(validators)}", 'info')
            
        except Exception as e:
            print_status(f"⚠️  Could not parse validator list: {e}", 'warning')
    
    print_status("\n📋 To verify later:", 'info')
    print_status('   python backend/qie_validator_manager.py verify', 'info')
    print_status('   Or visit: https://mainnet.qie.digital/validators', 'info')
    
    return False

def main():
    """Main setup flow"""
    print_status("\n" + "="*60, 'info')
    print_status("🚀 ValiGuard AI - QIE Validator Setup", 'info')
    print_status("="*60 + "\n", 'info')
    
    # Step 1: Check QIE installation
    platform, prefix = check_qie_installation()
    if not platform:
        sys.exit(1)
    
    # Step 2: Check wallet
    has_wallet, wallets = check_wallet()
    if not has_wallet:
        sys.exit(1)
    
    # Get wallet address
    wallet_address = wallets[0].get('address') if wallets else None
    if not wallet_address:
        print_status("❌ Could not get wallet address", 'error')
        sys.exit(1)
    
    # Step 3: Check balance
    has_balance = get_wallet_balance(wallet_address)
    if not has_balance:
        print_status("\n⚠️  Cannot proceed without sufficient balance", 'warning')
        sys.exit(1)
    
    # Step 4: Get validator public key
    pubkey = get_validator_pubkey()
    if not pubkey:
        sys.exit(1)
    
    # Step 5: Create validator.json
    if not create_validator_json(pubkey):
        sys.exit(1)
    
    # Step 6: Register validator
    if not register_validator():
        sys.exit(1)
    
    # Step 7: Verify validator
    verify_validator()
    
    # Final instructions
    print_status("\n" + "="*60, 'success')
    print_status("🎉 Validator Registration Complete!", 'success')
    print_status("="*60, 'success')
    print_status("\n📋 Next Steps:", 'info')
    print_status("   1. Wait 5-10 minutes for blockchain confirmation", 'info')
    print_status("   2. Verify status: python backend/qie_validator_manager.py verify", 'info')
    print_status("   3. Check explorer: https://mainnet.qie.digital/validators", 'info')
    print_status("   4. Monitor your validator's performance", 'info')
    print_status("\n📚 Documentation:", 'info')
    print_status("   See: docs/QIE_VALIDATOR_COMPLETE_GUIDE.md", 'info')
    print_status("="*60 + "\n", 'success')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print_status("\n❌ Setup cancelled by user", 'error')
        sys.exit(1)
    except Exception as e:
        print_status(f"\n❌ Setup failed: {e}", 'error')
        sys.exit(1)
