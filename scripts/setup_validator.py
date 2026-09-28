
import subprocess
import json
import time
import sys
import re
import os

def run_wsl_command(cmd, input_text=None):
    """Run a command in WSL and return output."""
    wsl_cmd = ["wsl", "bash", "-c", cmd]
    try:
        process = subprocess.Popen(
            wsl_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        stdout, stderr = process.communicate(input=input_text)
        return stdout.strip(), stderr.strip(), process.returncode
    except Exception as e:
        return "", str(e), -1

def get_validator_address():
    print("📋 Getting validator info...")
    cmd = "~/.qie/qied keys show validator --home ~/.qieMainnetNode --output json"
    stdout, stderr, code = run_wsl_command(cmd)
    
    if code != 0:
         # Fallback regex
         match = re.search(r'address:\s*(\w+)', stdout)
         if match: return match.group(1), ""
         return "qie1ycctf3drjw6fzjpsdlxt6hh0muaasyhtl9ndld", ""

    try:
        json_start = stdout.find('{')
        json_end = stdout.rfind('}') + 1
        if json_start >= 0:
            data = json.loads(stdout[json_start:json_end])
            return data.get('address'), data.get('pubkey')
    except:
        return "qie1ycctf3drjw6fzjpsdlxt6hh0muaasyhtl9ndld", ""

def check_balance(address):
    # Updated to Chain ID qie_1983-1 for Testnet
    cmd = f"~/.qie/qied query bank balances {address} --chain-id qie_1983-1 --node tcp://localhost:26657 --output json"
    stdout, stderr, code = run_wsl_command(cmd)
    try:
        json_start = stdout.find('{')
        json_end = stdout.rfind('}') + 1
        if json_start >= 0:
            data = json.loads(stdout[json_start:json_end])
            for b in data.get('balances', []):
                if b['denom'] == 'aqie':
                    return int(b['amount']) / 1e18
    except:
        pass
    return 0.0

def create_validator_json(pubkey_json):
    print("\n📋 Creating validator.json (Testnet Config)...")
    if isinstance(pubkey_json, dict):
        pubkey_str = json.dumps(pubkey_json)
    else:
        cmd = "~/.qie/qied tendermint show-validator --home ~/.qieMainnetNode"
        pubkey_str, _, _ = run_wsl_command(cmd)
    
    validator_data = {
        "pubkey": json.loads(pubkey_str) if "{" in pubkey_str else pubkey_str,
        "amount": "1000000000000000000aqie", # 1 QIE
        "moniker": "valiguard-ai-validator",
        "identity": "",
        "website": "https://github.com/sunnyshin8/ValiGuard-AI",
        "security": "",
        "details": "ValiGuard AI - Testnet Validator",
        "commission-rate": "0.1",
        "commission-max-rate": "0.2",
        "commission-max-change-rate": "0.01",
        "min-self-delegation": "1"
    }
    
    json_content = json.dumps(validator_data, indent=2)
    cmd = f"cat > ~/.qieMainnetNode/validator.json << 'EOF'\n{json_content}\nEOF"
    run_wsl_command(cmd)
    print("✅ validator.json created")

def register_validator():
    print("\n📡 Submitting create-validator transaction (Chain ID: qie_1983-1)...")
    cmd = ("~/.qie/qied tx staking create-validator ~/.qieMainnetNode/validator.json "
           "--from validator --chain-id qie_1983-1 --home ~/.qieMainnetNode "
           "--node tcp://localhost:26657 --gas auto --gas-adjustment 1.5 "
           "--gas-prices 10000000000aqie -y")
    
    stdout, stderr, code = run_wsl_command(cmd, input_text="Shin@123\n")
    print(stdout)
    if code == 0:
        print("\n✅ Transaction submitted! Wait for block confirmation.")
    else:
        print(f"\n❌ Error submitting transaction: {stderr}")

def main():
    print("🚀 ValiGuard AI - Validator Setup (Testnet - Fixed MainnetNode)")
    
    address, pubkey = get_validator_address()
    print(f"Address: {address}")
    
    # Check Balance
    bal = check_balance(address)
    print(f"\nCurrent Balance: {bal:>20.6f} QIE")
    
    if bal < 1.0:
        print("❌ Insufficient balance. You need at least 1 QIE.")
        print("   Please use the faucet (Chain ID: 1983 or qie-testnet).")
        return

    # Auto-Register (No prompt for automation)
    print("\n--- STEP 2: REGISTRATION ---")
    create_validator_json(pubkey)
    register_validator()

if __name__ == "__main__":
    main()
