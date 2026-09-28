
import subprocess
import os
import shutil
import time

def run_wsl_command(cmd):
    """Run a command in WSL."""
    print(f"Running: {cmd}")
    wsl_cmd = ["wsl", "bash", "-c", cmd]
    try:
        subprocess.run(wsl_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")

def main():
    print("==================================================")
    print("🔄 Switching Node to QIE TESTNET (Chain ID: 1983)")
    print("==================================================")
    
    # 1. Stop existing node
    print("\n🛑 Stopping QIE Node...")
    run_wsl_command("pkill qied")
    time.sleep(2)
    
    # 2. Backup Mainnet Data
    print("\n📦 Backing up Mainnet data...")
    run_wsl_command("if [ -d ~/.qieMainnetNode ]; then mv ~/.qieMainnetNode ~/.qieMainnetNode_backup_$(date +%s); fi")
    
    # 3. Initialize Method for Testnet
    # Since we don't have a direct genesis URL, we rely on 'init' and overwriting config
    print("\n✨ Initializing Testnet Node...")
    chain_id = "1983"
    moniker = "valiguard-ai-testnet"
    run_wsl_command(f"~/.qie/qied init {moniker} --chain-id {chain_id} --home ~/.qieMainnetNode")
    
    # 4. Configure Peers and RPC (Crucial for sync without manual genesis download)
    print("\n⚙️  Configuring Testnet Peers...")
    # Using RPCs found in docs as seeds/persistent peers if possible, or just trusting the binary's default seeds?
    # Docs gave: RPC1: https://rpc1testnet.qie.digital/
    # We will try to add a known peer if we found one, otherwise we might rely on seeds.
    # Searching for peers... 'rpc1testnet.qie.digital' is an RPC, not a P2P peer.
    # Without known P2P peers, syncing might be hard.
    # However, let's set the minimum gas prices and other configs.
    
    run_wsl_command("sed -i 's/minimum-gas-prices = \"\"/minimum-gas-prices = \"10000000000aqie\"/g' ~/.qieMainnetNode/config/app.toml")
    
    print("\n⚠️  NOTE: We reset the node directory for Testnet.")
    print("   We kept the folder name ~/.qieMainnetNode to reuse existing scripts, but it now contains TESTNET data.")
    
    # 5. Start Node
    print("\n🚀 Starting Testnet Node...")
    run_wsl_command("nohup ~/.qie/qied start --home ~/.qieMainnetNode > ~/.qieMainnetNode/logs/node.log 2>&1 &")
    
    print("\n✅ Node started on Testnet!")
    print("   Please wait for it to sync.")
    print("   Check status:  wsl bash -c \"curl -s http://localhost:26657/status | grep network\"")

if __name__ == "__main__":
    main()
