
# QIE Validator Setup Script
# This script interacts with the qied binary
import subprocess
import json
import time

def run_command(cmd):
    try:
        result = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), -1

def setup_genesis():
    # Attempt to copy genesis again, with explicit paths
    print("Copying genesis...")
    cmd = "cp /tmp/tempnode/config/genesis.json ~/.qieMainnetNode/config/genesis.json"
    o, e, c = run_command(cmd)
    if c != 0:
        print(f"Error copying genesis: {e}")
        # Try creating dir if missing
        run_command("mkdir -p ~/.qieMainnetNode/config")
        o, e, c = run_command(cmd)
        if c != 0:
           print(f"Retry failed: {e}")
           return False
    return True

if __name__ == "__main__":
    setup_genesis()
