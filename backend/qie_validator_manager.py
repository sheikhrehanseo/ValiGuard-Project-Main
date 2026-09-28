#!/usr/bin/env python3
"""
qie_validator_manager.py
QIE Validator Registration and Management

Handles validator registration, verification, and monitoring:
- Get validator public key
- Create validator configuration
- Register validator on-chain
- Verify validator status
- Monitor validator performance

Reference: 
- Register: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/8.-register-your-validator
- Verify: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/9.-verify-your-validator
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('qie_validator_manager')


@dataclass
class ValidatorConfig:
    """Validator configuration"""
    # Public key (from tendermint show-validator)
    pubkey: Dict[str, str] = None
    
    # Staking amount (in aqie - smallest unit)
    # 1 QIE = 1,000,000,000,000,000,000 aqie (10^18)
    amount: str = "10000000000000000000000aqie"  # 10,000 QIE
    
    # Validator information
    moniker: str = "valiguard-ai-validator"
    identity: str = ""  # Keybase identity (optional)
    website: str = "https://github.com/sunnyshin8/ValiGuard-AI"
    security: str = ""  # Security contact
    details: str = "ValiGuard AI - Cross-chain bridge monitoring and anomaly detection"
    
    # Commission rates (as decimals)
    commission_rate: str = "0.1"  # 10%
    commission_max_rate: str = "0.2"  # 20%
    commission_max_change_rate: str = "0.01"  # 1% per day
    
    # Minimum self-delegation
    min_self_delegation: str = "1000"
    
    # Chain configuration
    chain_id: str = "qie_1990-1"
    
    # Node configuration
    qie_home: str = None
    qied_binary: str = None
    rpc_endpoint: str = "tcp://localhost:26657"
    
    # Wallet configuration
    wallet_name: str = "validator"
    
    # Gas configuration
    gas: str = "auto"
    gas_adjustment: str = "1.5"
    gas_prices: str = "10000000000aqie"
    
    def __post_init__(self):
        if self.qie_home is None:
            self.qie_home = os.path.expanduser('~/.qieMainnetNode')
        if self.qied_binary is None:
            self.qied_binary = os.path.expanduser('~/.qie/qied')


class QIEValidatorManager:
    """Manager for QIE validator operations"""
    
    def __init__(self, config: Optional[ValidatorConfig] = None):
        """
        Initialize validator manager
        
        Args:
            config: Validator configuration (uses defaults if None)
        """
        self.config = config or ValidatorConfig()
        
        # Validate binary exists
        if not os.path.exists(self.config.qied_binary):
            logger.warning(f"⚠️  QIE binary not found at {self.config.qied_binary}")
    
    def get_validator_pubkey(self) -> Optional[Dict[str, str]]:
        """
        Get validator public key from tendermint
        
        Returns:
            Public key dict or None if failed
        """
        try:
            logger.info("🔑 Getting validator public key...")
            
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'tendermint',
                    'show-validator',
                    '--home', self.config.qie_home
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Failed to get validator public key: {result.stderr}")
                return None
            
            # Parse public key JSON
            pubkey = json.loads(result.stdout.strip())
            
            logger.info(f"✅ Validator public key retrieved")
            logger.info(f"   Type: {pubkey.get('@type', 'unknown')}")
            logger.info(f"   Key: {pubkey.get('key', 'unknown')}")
            
            return pubkey
            
        except Exception as e:
            logger.error(f"❌ Failed to get validator public key: {e}")
            return None
    
    def create_validator_json(self, output_path: Optional[str] = None) -> bool:
        """
        Create validator.json configuration file
        
        Args:
            output_path: Path to save validator.json (default: $HOME/.qieMainnetNode/validator.json)
            
        Returns:
            True if successful
        """
        try:
            logger.info("📄 Creating validator configuration file...")
            
            # Get public key if not set
            if self.config.pubkey is None:
                pubkey = self.get_validator_pubkey()
                if pubkey is None:
                    logger.error("❌ Cannot create validator config without public key")
                    return False
                self.config.pubkey = pubkey
            
            # Set default output path
            if output_path is None:
                output_path = os.path.join(self.config.qie_home, 'validator.json')
            
            # Create validator configuration
            validator_config = {
                "pubkey": self.config.pubkey,
                "amount": self.config.amount,
                "moniker": self.config.moniker,
                "identity": self.config.identity,
                "website": self.config.website,
                "security": self.config.security,
                "details": self.config.details,
                "commission-rate": self.config.commission_rate,
                "commission-max-rate": self.config.commission_max_rate,
                "commission-max-change-rate": self.config.commission_max_change_rate,
                "min-self-delegation": self.config.min_self_delegation
            }
            
            # Save to file
            with open(output_path, 'w') as f:
                json.dump(validator_config, f, indent=2)
            
            logger.info(f"✅ Validator configuration created: {output_path}")
            self._print_validator_config(validator_config)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create validator configuration: {e}")
            return False
    
    def _print_validator_config(self, config: Dict[str, Any]):
        """Print validator configuration summary"""
        print("\n" + "="*60)
        print("📋 Validator Configuration")
        print("="*60)
        print(f"Moniker:              {config['moniker']}")
        print(f"Website:              {config['website']}")
        print(f"Details:              {config['details']}")
        print(f"Staking Amount:       {config['amount']}")
        print(f"Commission Rate:      {config['commission-rate']} (10%)")
        print(f"Max Commission:       {config['commission-max-rate']} (20%)")
        print(f"Max Change Rate:      {config['commission-max-change-rate']} (1%/day)")
        print(f"Min Self-Delegation:  {config['min-self-delegation']}")
        print("="*60 + "\n")
    
    def register_validator(self, validator_json_path: Optional[str] = None) -> bool:
        """
        Register validator on-chain (create-validator transaction)
        
        Args:
            validator_json_path: Path to validator.json (default: $HOME/.qieMainnetNode/validator.json)
            
        Returns:
            True if successful
        """
        try:
            logger.info("🚀 Registering validator on-chain...")
            
            # Set default path
            if validator_json_path is None:
                validator_json_path = os.path.join(self.config.qie_home, 'validator.json')
            
            # Check if file exists
            if not os.path.exists(validator_json_path):
                logger.error(f"❌ Validator config not found: {validator_json_path}")
                logger.info("💡 Run create_validator_json() first")
                return False
            
            # Check wallet balance first
            logger.info("💰 Checking wallet balance...")
            balance_info = self.get_wallet_balance()
            if balance_info is None:
                logger.warning("⚠️  Could not verify wallet balance")
            else:
                logger.info(f"   Balance: {balance_info.get('balance', 'unknown')}")
            
            print("\n" + "="*60)
            print("⚠️  IMPORTANT: Validator Registration")
            print("="*60)
            print("You are about to submit a create-validator transaction.")
            print("This will:")
            print(f"  - Stake {self.config.amount} from your wallet")
            print(f"  - Register '{self.config.moniker}' as a validator")
            print(f"  - Set commission rate to {self.config.commission_rate}")
            print("\nYou will be prompted for your wallet password.")
            print("="*60)
            
            confirm = input("\n🔐 Proceed with validator registration? (yes/no): ")
            if confirm.lower() != 'yes':
                logger.info("❌ Validator registration cancelled")
                return False
            
            # Submit create-validator transaction
            logger.info("📡 Submitting create-validator transaction...")
            
            cmd = [
                self.config.qied_binary,
                'tx', 'staking', 'create-validator',
                validator_json_path,
                '--from', self.config.wallet_name,
                '--chain-id', self.config.chain_id,
                '--home', self.config.qie_home,
                '--node', self.config.rpc_endpoint,
                '--gas', self.config.gas,
                '--gas-adjustment', self.config.gas_adjustment,
                '--gas-prices', self.config.gas_prices,
                '-y'  # Auto-confirm (password still required)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Validator registration failed: {result.stderr}")
                return False
            
            # Parse transaction result
            try:
                tx_result = json.loads(result.stdout)
                tx_hash = tx_result.get('txhash', 'unknown')
                
                logger.info("✅ Validator registration transaction submitted!")
                logger.info(f"   Transaction Hash: {tx_hash}")
                logger.info("\n⏳ Waiting for transaction to be confirmed...")
                logger.info("   This may take a few minutes...")
                
                # Wait and check transaction
                import time
                time.sleep(10)
                
                tx_info = self.query_transaction(tx_hash)
                if tx_info and tx_info.get('code') == 0:
                    logger.info("✅ Validator registered successfully!")
                    return True
                else:
                    logger.warning("⚠️  Transaction submitted but status unclear")
                    logger.info("   Check validator status with: verify_validator()")
                    return True
                    
            except json.JSONDecodeError:
                # Old format output
                logger.info("✅ Validator registration transaction submitted!")
                logger.info(result.stdout)
                return True
            
        except Exception as e:
            logger.error(f"❌ Failed to register validator: {e}")
            return False
    
    def verify_validator(self) -> Optional[Dict[str, Any]]:
        """
        Verify validator is registered and get status
        
        Returns:
            Validator information or None if not found
        """
        try:
            logger.info("🔍 Verifying validator status...")
            
            # Get validator operator address
            operator_address = self.get_validator_operator_address()
            if operator_address is None:
                logger.error("❌ Could not get validator operator address")
                return None
            
            # Query validator
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'query', 'staking', 'validator',
                    operator_address,
                    '--chain-id', self.config.chain_id,
                    '--node', self.config.rpc_endpoint,
                    '--output', 'json'
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Validator not found: {result.stderr}")
                return None
            
            validator_info = json.loads(result.stdout)
            
            logger.info("✅ Validator found!")
            self._print_validator_status(validator_info)
            
            return validator_info
            
        except Exception as e:
            logger.error(f"❌ Failed to verify validator: {e}")
            return None
    
    def _print_validator_status(self, validator_info: Dict[str, Any]):
        """Print validator status information"""
        operator_address = validator_info.get('operator_address', 'unknown')
        moniker = validator_info.get('description', {}).get('moniker', 'unknown')
        status = validator_info.get('status', 'unknown')
        jailed = validator_info.get('jailed', False)
        tokens = validator_info.get('tokens', '0')
        delegator_shares = validator_info.get('delegator_shares', '0')
        commission_rate = validator_info.get('commission', {}).get('commission_rates', {}).get('rate', '0')
        
        print("\n" + "="*60)
        print("✅ Validator Status")
        print("="*60)
        print(f"Operator Address:  {operator_address}")
        print(f"Moniker:           {moniker}")
        print(f"Status:            {status}")
        print(f"Jailed:            {'Yes ❌' if jailed else 'No ✅'}")
        print(f"Tokens:            {tokens}")
        print(f"Delegator Shares:  {delegator_shares}")
        print(f"Commission Rate:   {commission_rate}")
        print("="*60 + "\n")
    
    def list_all_validators(self) -> List[Dict[str, Any]]:
        """
        List all validators in the network
        
        Returns:
            List of validator information
        """
        try:
            logger.info("📋 Fetching all validators...")
            
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'query', 'staking', 'validators',
                    '--chain-id', self.config.chain_id,
                    '--node', self.config.rpc_endpoint,
                    '--output', 'json'
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Failed to fetch validators: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            validators = data.get('validators', [])
            
            logger.info(f"✅ Found {len(validators)} validators")
            
            # Print summary
            print("\n" + "="*60)
            print(f"📋 Network Validators ({len(validators)} total)")
            print("="*60)
            for i, val in enumerate(validators[:10], 1):  # Show first 10
                moniker = val.get('description', {}).get('moniker', 'unknown')
                status = val.get('status', 'unknown')
                jailed = val.get('jailed', False)
                print(f"{i}. {moniker} - Status: {status} - Jailed: {jailed}")
            
            if len(validators) > 10:
                print(f"... and {len(validators) - 10} more")
            print("="*60 + "\n")
            
            return validators
            
        except Exception as e:
            logger.error(f"❌ Failed to list validators: {e}")
            return []
    
    def get_validator_operator_address(self) -> Optional[str]:
        """
        Get validator operator address from wallet
        
        Returns:
            Operator address or None
        """
        try:
            # Get wallet address
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'keys', 'show',
                    self.config.wallet_name,
                    '--bech32', 'val',
                    '--home', self.config.qie_home,
                    '--output', 'json'
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # Try without --bech32 flag (older versions)
                result = subprocess.run(
                    [
                        self.config.qied_binary,
                        'keys', 'show',
                        self.config.wallet_name,
                        '--home', self.config.qie_home,
                        '--output', 'json'
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode != 0:
                    logger.error(f"❌ Failed to get validator address: {result.stderr}")
                    return None
            
            data = json.loads(result.stdout)
            
            # Try different field names
            operator_address = (
                data.get('address') or 
                data.get('operator_address') or
                data.get('validator_address')
            )
            
            return operator_address
            
        except Exception as e:
            logger.error(f"❌ Failed to get validator operator address: {e}")
            return None
    
    def get_wallet_balance(self) -> Optional[Dict[str, Any]]:
        """
        Get wallet balance
        
        Returns:
            Balance information or None
        """
        try:
            # Get wallet address
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'keys', 'show',
                    self.config.wallet_name,
                    '--home', self.config.qie_home,
                    '--output', 'json'
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Failed to get wallet address: {result.stderr}")
                return None
            
            wallet_data = json.loads(result.stdout)
            wallet_address = wallet_data.get('address')
            
            # Query balance
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'query', 'bank', 'balances',
                    wallet_address,
                    '--chain-id', self.config.chain_id,
                    '--node', self.config.rpc_endpoint,
                    '--output', 'json'
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Failed to query balance: {result.stderr}")
                return None
            
            balance_data = json.loads(result.stdout)
            balances = balance_data.get('balances', [])
            
            # Find aqie balance
            aqie_balance = 0
            for balance in balances:
                if balance.get('denom') == 'aqie':
                    aqie_balance = int(balance.get('amount', 0))
                    break
            
            # Convert to QIE (1 QIE = 10^18 aqie)
            qie_balance = aqie_balance / (10**18)
            
            return {
                'address': wallet_address,
                'balance': f"{qie_balance:.6f} QIE",
                'balance_aqie': aqie_balance,
                'balances': balances
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get wallet balance: {e}")
            return None
    
    def query_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """
        Query transaction by hash
        
        Args:
            tx_hash: Transaction hash
            
        Returns:
            Transaction information or None
        """
        try:
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'query', 'tx',
                    tx_hash,
                    '--chain-id', self.config.chain_id,
                    '--node', self.config.rpc_endpoint,
                    '--output', 'json'
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return None
            
            return json.loads(result.stdout)
            
        except Exception as e:
            logger.error(f"❌ Failed to query transaction: {e}")
            return None
    
    def check_validator_on_explorer(self):
        """Print validator explorer link"""
        print("\n" + "="*60)
        print("🌐 Check Validator on Explorer")
        print("="*60)
        print("Visit the QIE explorer to see all validators:")
        print("   https://mainnet.qie.digital/validators")
        print(f"\nSearch for your validator: {self.config.moniker}")
        print("="*60 + "\n")
    
    def print_validator_instructions(self):
        """Print validator registration instructions"""
        print("\n" + "="*60)
        print("📚 Validator Registration Guide")
        print("="*60)
        print("\n🔗 Documentation:")
        print("   - Register: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/8.-register-your-validator")
        print("   - Verify:   https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/9.-verify-your-validator")
        print("\n📋 Registration Steps:")
        print("   1. Get validator public key:")
        print("      validator_manager.get_validator_pubkey()")
        print("\n   2. Create validator configuration:")
        print("      validator_manager.create_validator_json()")
        print("\n   3. Register validator on-chain:")
        print("      validator_manager.register_validator()")
        print("\n   4. Verify validator status:")
        print("      validator_manager.verify_validator()")
        print("\n   5. Check on explorer:")
        print("      https://mainnet.qie.digital/validators")
        print("="*60 + "\n")
    
    def run_full_registration(self) -> bool:
        """
        Run complete validator registration process
        
        Returns:
            True if successful
        """
        print("\n" + "="*60)
        print("🚀 QIE Validator Registration Process")
        print("="*60 + "\n")
        
        # Step 1: Get public key
        print("🔑 Step 1/4: Getting validator public key...")
        pubkey = self.get_validator_pubkey()
        if pubkey is None:
            logger.error("❌ Registration aborted: Could not get public key")
            return False
        
        # Step 2: Create validator.json
        print("\n📄 Step 2/4: Creating validator configuration...")
        if not self.create_validator_json():
            logger.error("❌ Registration aborted: Could not create validator config")
            return False
        
        # Step 3: Register validator
        print("\n🚀 Step 3/4: Registering validator on-chain...")
        if not self.register_validator():
            logger.error("❌ Registration failed")
            return False
        
        # Step 4: Verify validator
        print("\n✅ Step 4/4: Verifying validator status...")
        import time
        time.sleep(5)  # Wait for blockchain to process
        
        validator_info = self.verify_validator()
        if validator_info is None:
            logger.warning("⚠️  Could not verify validator immediately")
            logger.info("   Try again in a few minutes with: verify_validator()")
        
        # Print next steps
        self.check_validator_on_explorer()
        
        logger.info("🎉 Validator registration process completed!")
        return True


def main():
    """Main entry point for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='QIE Validator Registration and Management'
    )
    
    parser.add_argument(
        'command',
        choices=[
            'pubkey', 'create-config', 'register', 'verify',
            'list', 'balance', 'explorer', 'instructions', 'full'
        ],
        help='Command to execute'
    )
    
    parser.add_argument('--moniker', help='Validator moniker')
    parser.add_argument('--home', help='QIE home directory')
    parser.add_argument('--wallet', help='Wallet name (default: validator)')
    parser.add_argument('--amount', help='Staking amount in aqie')
    
    args = parser.parse_args()
    
    # Create config
    config = ValidatorConfig()
    if args.moniker:
        config.moniker = args.moniker
    if args.home:
        config.qie_home = args.home
    if args.wallet:
        config.wallet_name = args.wallet
    if args.amount:
        config.amount = args.amount
    
    # Create manager
    manager = QIEValidatorManager(config)
    
    # Execute command
    if args.command == 'pubkey':
        pubkey = manager.get_validator_pubkey()
        if pubkey:
            print(json.dumps(pubkey, indent=2))
            sys.exit(0)
        sys.exit(1)
    
    elif args.command == 'create-config':
        success = manager.create_validator_json()
        sys.exit(0 if success else 1)
    
    elif args.command == 'register':
        success = manager.register_validator()
        sys.exit(0 if success else 1)
    
    elif args.command == 'verify':
        validator_info = manager.verify_validator()
        if validator_info:
            print(json.dumps(validator_info, indent=2))
            sys.exit(0)
        sys.exit(1)
    
    elif args.command == 'list':
        validators = manager.list_all_validators()
        sys.exit(0)
    
    elif args.command == 'balance':
        balance_info = manager.get_wallet_balance()
        if balance_info:
            print(json.dumps(balance_info, indent=2))
            sys.exit(0)
        sys.exit(1)
    
    elif args.command == 'explorer':
        manager.check_validator_on_explorer()
        sys.exit(0)
    
    elif args.command == 'instructions':
        manager.print_validator_instructions()
        sys.exit(0)
    
    elif args.command == 'full':
        success = manager.run_full_registration()
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
