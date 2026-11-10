
import subprocess
import json
import re

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
            encoding='utf-8', # Force UTF-8 for WSL interaction
            errors='replace'
        )
        
        stdout, stderr = process.communicate(input=input_text)
        
        return stdout.strip(), stderr.strip(), process.returncode
    except Exception as e:
        return "", str(e), -1

def get_validator_address():
    print("Getting validator address...")
    cmd = "~/.qie/qied keys show validator --home ~/.qieMainnetNode --output json"
    stdout, stderr, code = run_wsl_command(cmd)
    
    if code != 0:
        if "address" in stdout:
             match = re.search(r'address:\s*(\w+)', stdout)
             if match:
                 return match.group(1)
    
    try:
        json_start = stdout.find('{')
        json_end = stdout.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            json_str = stdout[json_start:json_end]
            data = json.loads(json_str)
            return data.get('address')
    except Exception as e:
        print(f"Error parsing address JSON: {e}")
        pass
        
    print("Warning: Could not detect address dynamically. Output was:")
    print(stdout)
    return "qie1ycctf3drjw6fzjpsdlxt6hh0muaasyhtl9ndld"

def check_balance(address):
    print(f"\nChecking balance for {address}...")
    cmd = f"~/.qie/qied query bank balances {address} --chain-id qie_1990-1 --node tcp://localhost:26657 --output json"
    stdout, stderr, code = run_wsl_command(cmd)
    
    try:
        json_start = stdout.find('{')
        json_end = stdout.rfind('}') + 1
        if json_start >= 0:
            data = json.loads(stdout[json_start:json_end])
            balances = data.get('balances', [])
            for b in balances:
                if b['denom'] == 'aqie':
                    amount = int(b['amount'])
                    qie = amount / 1e18
                    return qie
    except Exception as e:
        print(f"Balance check error: {e}")
        pass
            
    return 0.0

def main():
    print("ValiGuard AI - Validator Helper (Python Version)")
    
    # 1. Get Address
    address = get_validator_address()
    print(f"Address: {address}")
    
    # Dashboard authentication uses MetaMask nonce signatures and JWTs.
    # Validator key management remains with the node's local keyring.
    print("\nConnect your existing MetaMask wallet in the dashboard to sign in.")

    # 2. Check Balance
    balance = check_balance(address)
    print(f"\nBalance: {balance} QIE")
    
    if balance < 10000:
        print("\nInsufficient balance for validator (Need 10,000 QIE)")
        print(f"   Please send QIE to: {address}")
        print("   See guide: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins")
    else:
        print("\nBalance sufficient!")

if __name__ == "__main__":
    main()
