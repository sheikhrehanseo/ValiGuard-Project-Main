#!/usr/bin/env python3

"""
qie_wallet_manager.py
QIE Validator Wallet Management Utility

Provides Python interface for wallet operations:
- List wallets
- Get wallet details
- Query balance
- Export wallet info
- Manage validator operations

Usage:
    python backend/qie_wallet_manager.py list
    python backend/qie_wallet_manager.py balance <address>
    python backend/qie_wallet_manager.py info <wallet_name>
"""

import os
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('qie_wallet_manager')


class QIEWalletManager:
    """Manager for QIE validator wallet operations"""
    
    def __init__(self, home: Optional[str] = None):
        """
        Initialize wallet manager
        
        Args:
            home: QIE home directory (default: ~/.qieMainnetNode)
        """
        self.home = home or os.path.expanduser('~/.qieMainnetNode')
        self.qied_binary = os.path.expanduser('~/.qie/qied')
        
        # Validate setup
        if not os.path.exists(self.qied_binary):
            raise FileNotFoundError(f"QIE binary not found: {self.qied_binary}")
        if not os.path.exists(self.home):
            raise FileNotFoundError(f"QIE home not found: {self.home}")
        
        logger.info(f"Initialized with home: {self.home}")
    
    def _run_qied(self, *args) -> Dict[str, Any]:
        """
        Run qied command and return parsed output
        
        Args:
            *args: Command arguments (e.g., 'keys', 'list')
            
        Returns:
            Command output as dict/string
        """
        try:
            cmd = [self.qied_binary, '--home', self.home] + list(args)
            logger.debug(f"Running: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Command failed: {result.stderr}")
            
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError("Command timeout")
        except Exception as e:
            logger.error(f"Command error: {e}")
            raise
    
    def list_wallets(self) -> List[Dict[str, str]]:
        """
        List all available wallets
        
        Returns:
            List of wallet info dicts
        """
        logger.info("Listing wallets...")
        
        output = self._run_qied('keys', 'list', '--output', 'json')
        
        try:
            wallets = json.loads(output)
            logger.info(f"Found {len(wallets)} wallet(s)")
            return wallets
        except json.JSONDecodeError:
            # Fallback to text parsing
            wallets = []
            for line in output.split('\n'):
                if 'name:' in line:
                    wallets.append({'raw': line})
            return wallets
    
    def get_wallet_info(self, wallet_name: str) -> Dict[str, str]:
        """
        Get detailed info for a wallet
        
        Args:
            wallet_name: Name of wallet
            
        Returns:
            Wallet information
        """
        logger.info(f"Getting info for wallet: {wallet_name}")
        
        output = self._run_qied('keys', 'show', wallet_name, '--output', 'json')
        
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # Parse text format
            info = {}
            for line in output.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    info[key.strip()] = val.strip()
            return info
    
    def get_balance(self, address: str, denom: str = 'uqie') -> Dict[str, str]:
        """
        Query account balance
        
        Args:
            address: Wallet address
            denom: Token denomination (default: uqie)
            
        Returns:
            Balance info
        """
        logger.info(f"Querying balance for: {address}")
        
        output = self._run_qied(
            'query', 'bank', 'balances', address,
            '--output', 'json'
        )
        
        try:
            data = json.loads(output)
            balances = data.get('balances', [])
            
            for balance in balances:
                if balance.get('denom') == denom:
                    return {
                        'denom': denom,
                        'amount': balance.get('amount', '0'),
                        'amount_qie': str(int(balance.get('amount', 0)) / 1e18)
                    }
            
            return {'denom': denom, 'amount': '0', 'amount_qie': '0'}
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Error parsing balance: {e}")
            return {'error': str(e)}
    
    def get_validator_info(self, validator_address: str) -> Dict[str, Any]:
        """
        Get validator information
        
        Args:
            validator_address: Validator operator address
            
        Returns:
            Validator info
        """
        logger.info(f"Getting validator info: {validator_address}")
        
        output = self._run_qied(
            'query', 'staking', 'validator', validator_address,
            '--output', 'json'
        )
        
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {'raw': output}
    
    def get_all_validators(self) -> List[Dict[str, Any]]:
        """
        List all network validators
        
        Returns:
            List of validator info
        """
        logger.info("Getting all validators...")
        
        output = self._run_qied(
            'query', 'staking', 'validators',
            '--output', 'json'
        )
        
        try:
            data = json.loads(output)
            validators = data.get('validators', [])
            logger.info(f"Found {len(validators)} validators")
            return validators
        except json.JSONDecodeError:
            return []
    
    def get_node_status(self) -> Dict[str, Any]:
        """
        Get current node status
        
        Returns:
            Node status info
        """
        logger.info("Getting node status...")
        
        output = self._run_qied('status', '--output', 'json')
        
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {'raw': output}
    
    def export_wallet_info(self, wallet_name: str, output_file: Optional[str] = None) -> Dict[str, Any]:
        """
        Export complete wallet information to file
        
        Args:
            wallet_name: Name of wallet
            output_file: Output file path (default: <wallet_name>_info.json)
            
        Returns:
            Exported info
        """
        logger.info(f"Exporting wallet info: {wallet_name}")
        
        if not output_file:
            output_file = f"{wallet_name}_info.json"
        
        wallet_info = self.get_wallet_info(wallet_name)
        address = wallet_info.get('address', '')
        
        export_data = {
            'wallet_name': wallet_name,
            'address': address,
            'wallet_info': wallet_info,
            'balance': self.get_balance(address) if address else {},
            'node_status': self.get_node_status(),
            'exported_at': str(__import__('datetime').datetime.now().isoformat())
        }
        
        output_path = Path(output_file).expanduser()
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Exported to: {output_path}")
        return export_data


def main():
    """CLI interface"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python qie_wallet_manager.py list")
        print("  python qie_wallet_manager.py info <wallet_name>")
        print("  python qie_wallet_manager.py balance <address>")
        print("  python qie_wallet_manager.py validators")
        print("  python qie_wallet_manager.py status")
        print("  python qie_wallet_manager.py export <wallet_name> [output_file]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    try:
        manager = QIEWalletManager()
        
        if command == 'list':
            wallets = manager.list_wallets()
            print(json.dumps(wallets, indent=2))
        
        elif command == 'info':
            if len(sys.argv) < 3:
                print("Usage: qie_wallet_manager.py info <wallet_name>")
                sys.exit(1)
            wallet_name = sys.argv[2]
            info = manager.get_wallet_info(wallet_name)
            print(json.dumps(info, indent=2))
        
        elif command == 'balance':
            if len(sys.argv) < 3:
                print("Usage: qie_wallet_manager.py balance <address>")
                sys.exit(1)
            address = sys.argv[2]
            balance = manager.get_balance(address)
            print(json.dumps(balance, indent=2))
        
        elif command == 'validators':
            validators = manager.get_all_validators()
            print(json.dumps(validators, indent=2))
        
        elif command == 'status':
            status = manager.get_node_status()
            print(json.dumps(status, indent=2))
        
        elif command == 'export':
            if len(sys.argv) < 3:
                print("Usage: qie_wallet_manager.py export <wallet_name> [output_file]")
                sys.exit(1)
            wallet_name = sys.argv[2]
            output_file = sys.argv[3] if len(sys.argv) > 3 else None
            export_data = manager.export_wallet_info(wallet_name, output_file)
            print(json.dumps(export_data, indent=2))
        
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
