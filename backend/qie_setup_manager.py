#!/usr/bin/env python3
"""
qie_setup_manager.py
QIE Node Setup and Configuration Manager

Complete setup automation for QIE validator nodes including:
- System requirements validation
- Binary download and installation
- Node configuration
- Genesis initialization
- Docker support
- Monitoring and health checks

Reference: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/2.-install-qie-node
"""

import os
import sys
import json
import shutil
import platform
import subprocess
import logging
import requests
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from dataclasses import dataclass
import psutil

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('qie_setup_manager')


@dataclass
class SystemRequirements:
    """System requirements for QIE node"""
    min_cpu_cores: int = 2
    min_ram_gb: int = 4
    min_disk_gb: int = 100
    supported_os: List[str] = None
    
    def __post_init__(self):
        if self.supported_os is None:
            self.supported_os = ['Linux', 'Darwin', 'Windows']


@dataclass
class NodeConfig:
    """QIE Node configuration"""
    moniker: str = "valiguard-ai-validator"
    chain_id: str = "qie_1990-1"
    
    # Network ports
    rpc_port: int = 26657
    p2p_port: int = 26656
    grpc_port: int = 9090
    api_port: int = 1317
    
    # Endpoints
    rpc_endpoint: str = "http://localhost:26657"
    api_endpoint: str = "http://localhost:1317"
    
    # Directories
    qie_home: str = None
    config_dir: str = None
    data_dir: str = None
    logs_dir: str = None
    
    # Binary paths
    qied_binary: str = None
    
    # Network settings
    enable_cors: bool = True
    log_level: str = "info"
    
    # Peers and seeds
    persistent_peers: str = ""
    seeds: str = ""
    
    def __post_init__(self):
        if self.qie_home is None:
            self.qie_home = os.path.expanduser('~/.qieMainnetNode')
        if self.config_dir is None:
            self.config_dir = os.path.join(self.qie_home, 'config')
        if self.data_dir is None:
            self.data_dir = os.path.join(self.qie_home, 'data')
        if self.logs_dir is None:
            self.logs_dir = os.path.join(self.qie_home, 'logs')
        if self.qied_binary is None:
            self.qied_binary = os.path.expanduser('~/.qie/qied')


class QIESetupManager:
    """Manager for QIE node setup and configuration"""
    
    def __init__(self, config: Optional[NodeConfig] = None):
        """
        Initialize setup manager
        
        Args:
            config: Node configuration (uses defaults if None)
        """
        self.config = config or NodeConfig()
        self.requirements = SystemRequirements()
        self.system_info = self._get_system_info()
        
    def _get_system_info(self) -> Dict[str, Any]:
        """Get current system information"""
        return {
            'os': platform.system(),
            'os_version': platform.version(),
            'machine': platform.machine(),
            'cpu_cores': psutil.cpu_count(logical=False),
            'total_ram_gb': round(psutil.virtual_memory().total / (1024**3), 2),
            'available_ram_gb': round(psutil.virtual_memory().available / (1024**3), 2),
            'total_disk_gb': round(psutil.disk_usage('/').total / (1024**3), 2),
            'free_disk_gb': round(psutil.disk_usage('/').free / (1024**3), 2),
            'python_version': sys.version.split()[0]
        }
    
    def validate_system_requirements(self) -> Tuple[bool, List[str]]:
        """
        Validate system meets minimum requirements
        
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        # Check OS
        if self.system_info['os'] not in self.requirements.supported_os:
            issues.append(f"❌ Unsupported OS: {self.system_info['os']}")
        
        # Check CPU cores
        if self.system_info['cpu_cores'] < self.requirements.min_cpu_cores:
            issues.append(
                f"❌ Insufficient CPU cores: {self.system_info['cpu_cores']} "
                f"(minimum: {self.requirements.min_cpu_cores})"
            )
        
        # Check RAM
        if self.system_info['total_ram_gb'] < self.requirements.min_ram_gb:
            issues.append(
                f"❌ Insufficient RAM: {self.system_info['total_ram_gb']}GB "
                f"(minimum: {self.requirements.min_ram_gb}GB)"
            )
        
        # Check disk space
        if self.system_info['free_disk_gb'] < self.requirements.min_disk_gb:
            issues.append(
                f"❌ Insufficient disk space: {self.system_info['free_disk_gb']}GB "
                f"(minimum: {self.requirements.min_disk_gb}GB)"
            )
        
        is_valid = len(issues) == 0
        
        if is_valid:
            logger.info("✅ System requirements validated successfully")
            self._print_system_info()
        else:
            logger.error("❌ System requirements validation failed")
            for issue in issues:
                logger.error(issue)
        
        return is_valid, issues
    
    def _print_system_info(self):
        """Print system information"""
        print("\n" + "="*60)
        print("📊 System Information")
        print("="*60)
        print(f"OS:              {self.system_info['os']} ({self.system_info['machine']})")
        print(f"CPU Cores:       {self.system_info['cpu_cores']}")
        print(f"Total RAM:       {self.system_info['total_ram_gb']} GB")
        print(f"Available RAM:   {self.system_info['available_ram_gb']} GB")
        print(f"Total Disk:      {self.system_info['total_disk_gb']} GB")
        print(f"Free Disk:       {self.system_info['free_disk_gb']} GB")
        print(f"Python:          {self.system_info['python_version']}")
        print("="*60 + "\n")
    
    def download_qie_binary(self, force: bool = False) -> bool:
        """
        Download QIE binary from official repository
        
        Args:
            force: Force download even if binary exists
            
        Returns:
            True if successful
        """
        try:
            qie_dir = os.path.dirname(self.config.qied_binary)
            
            # Check if already exists
            if os.path.exists(self.config.qied_binary) and not force:
                logger.info(f"✅ QIE binary already exists at {self.config.qied_binary}")
                return True
            
            # Create directory
            os.makedirs(qie_dir, exist_ok=True)
            
            # Determine download URL based on OS
            os_type = self.system_info['os']
            machine = self.system_info['machine']
            
            # Official QIE releases ship a single Linux ELF binary named
            # `qied` per release — there are no Windows/macOS assets and no
            # published checksums (verified 2026-09 against
            # https://github.com/qieadmin/qiev3-mainnet, per docs.qie.digital).
            release_tag = os.getenv("QIE_RELEASE_TAG", "QIE-Mainnet-V6")
            download_url = (
                f"https://github.com/qieadmin/qiev3-mainnet/"
                f"releases/download/{release_tag}/qied"
            )

            if os_type != 'Linux':
                logger.error(
                    f"❌ QIE node binaries are Linux-only (no release asset for {os_type}). "
                    "Run the node inside WSL or a Linux VM — see https://docs.qie.digital"
                )
                return False

            # Confirm the asset exists before downloading 130+ MB
            if not self._verify_release_asset(download_url):
                return False

            logger.info(f"📥 Downloading QIE binary from {download_url}...")

            # Download binary
            response = requests.get(download_url, stream=True, timeout=300)
            response.raise_for_status()

            with open(self.config.qied_binary, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # No official checksums are published; validate the file is a
            # real ELF binary and not an HTML error page from a bad URL.
            if not self._validate_binary_file(self.config.qied_binary):
                os.remove(self.config.qied_binary)
                logger.error("❌ Downloaded file is not a valid qied binary")
                return False
            
            # Make executable (Unix-like systems)
            if os_type in ['Linux', 'Darwin']:
                os.chmod(self.config.qied_binary, 0o755)
            
            logger.info(f"✅ QIE binary downloaded to {self.config.qied_binary}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to download QIE binary: {e}")
            return False

    def _verify_release_asset(self, download_url: str) -> bool:
        """Check the release asset exists via a lightweight HEAD request."""
        try:
            response = requests.head(
                download_url, allow_redirects=True, timeout=30
            )
            if response.status_code == 200:
                return True
            logger.error(
                f"❌ Release asset not found ({response.status_code}): {download_url}. "
                "Check https://github.com/qieadmin/qiev3-mainnet/releases "
                "and set QIE_RELEASE_TAG if needed."
            )
            return False
        except requests.RequestException as e:
            logger.error(f"❌ Could not reach GitHub releases: {e}")
            return False

    def _validate_binary_file(self, path: str) -> bool:
        """Validate the downloaded qied file is a real ELF binary."""
        try:
            min_size = 10 * 1024 * 1024  # releases are ~130MB; anything smaller is wrong
            if os.path.getsize(path) < min_size:
                logger.error(f"❌ Downloaded file too small to be qied ({os.path.getsize(path)} bytes)")
                return False
            with open(path, 'rb') as f:
                magic = f.read(4)
            if magic != b'\x7fELF':
                logger.error("❌ Downloaded file is not an ELF binary (wrong file or error page)")
                return False
            return True
        except OSError as e:
            logger.error(f"❌ Could not validate downloaded binary: {e}")
            return False
    
    def install_qie_node(self) -> bool:
        """
        Install and setup QIE node
        
        Returns:
            True if successful
        """
        try:
            logger.info("🚀 Installing QIE node...")
            
            # Validate binary exists
            if not os.path.exists(self.config.qied_binary):
                logger.error(f"❌ QIE binary not found at {self.config.qied_binary}")
                return False
            
            # Validate binary
            result = subprocess.run(
                [self.config.qied_binary, 'version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error("❌ QIE binary validation failed")
                return False
            
            version = result.stdout.strip()
            logger.info(f"✅ QIE binary validated: {version}")
            
            # Create directories
            for directory in [self.config.qie_home, self.config.config_dir, 
                            self.config.data_dir, self.config.logs_dir]:
                os.makedirs(directory, exist_ok=True)
                logger.info(f"📁 Created directory: {directory}")
            
            logger.info("✅ QIE node installation completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to install QIE node: {e}")
            return False
    
    def create_node_config(self) -> bool:
        """
        Generate node configuration file
        
        Returns:
            True if successful
        """
        try:
            logger.info("⚙️  Creating node configuration...")
            
            config_file = os.path.join(self.config.config_dir, 'config.toml')
            app_config_file = os.path.join(self.config.config_dir, 'app.toml')
            
            # Check if already initialized
            if os.path.exists(config_file):
                logger.info(f"✅ Configuration already exists at {config_file}")
                return True
            
            # Initialize node
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'init',
                    self.config.moniker,
                    '--chain-id', self.config.chain_id,
                    '--home', self.config.qie_home
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Node initialization failed: {result.stderr}")
                return False
            
            logger.info(f"✅ Node initialized with moniker: {self.config.moniker}")
            
            # Modify config.toml
            self._update_config_toml(config_file)
            
            # Modify app.toml
            self._update_app_toml(app_config_file)
            
            logger.info("✅ Node configuration created successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create node configuration: {e}")
            return False
    
    def _update_config_toml(self, config_file: str):
        """Update config.toml with custom settings"""
        try:
            with open(config_file, 'r') as f:
                config_content = f.read()
            
            # Update RPC settings
            config_content = config_content.replace(
                'laddr = "tcp://127.0.0.1:26657"',
                f'laddr = "tcp://0.0.0.0:{self.config.rpc_port}"'
            )
            
            # Update P2P settings
            config_content = config_content.replace(
                'laddr = "tcp://0.0.0.0:26656"',
                f'laddr = "tcp://0.0.0.0:{self.config.p2p_port}"'
            )
            
            # Enable CORS
            if self.config.enable_cors:
                config_content = config_content.replace(
                    'cors_allowed_origins = []',
                    'cors_allowed_origins = ["*"]'
                )
            
            # Set log level
            config_content = config_content.replace(
                'log_level = "info"',
                f'log_level = "{self.config.log_level}"'
            )
            
            # Set persistent peers if provided
            if self.config.persistent_peers:
                config_content = config_content.replace(
                    'persistent_peers = ""',
                    f'persistent_peers = "{self.config.persistent_peers}"'
                )
            
            with open(config_file, 'w') as f:
                f.write(config_content)
            
            logger.info("✅ config.toml updated")
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to update config.toml: {e}")
    
    def _update_app_toml(self, app_config_file: str):
        """Update app.toml with custom settings"""
        try:
            with open(app_config_file, 'r') as f:
                config_content = f.read()
            
            # Update API settings
            config_content = config_content.replace(
                'enable = false',
                'enable = true',
                1  # Only first occurrence
            )
            
            config_content = config_content.replace(
                'address = "tcp://0.0.0.0:1317"',
                f'address = "tcp://0.0.0.0:{self.config.api_port}"'
            )
            
            # Update gRPC settings
            config_content = config_content.replace(
                'address = "0.0.0.0:9090"',
                f'address = "0.0.0.0:{self.config.grpc_port}"'
            )
            
            with open(app_config_file, 'w') as f:
                f.write(config_content)
            
            logger.info("✅ app.toml updated")
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to update app.toml: {e}")
    
    def initialize_genesis(self, genesis_url: Optional[str] = None) -> bool:
        """
        Initialize genesis file
        
        Args:
            genesis_url: URL to download genesis file (optional)
            
        Returns:
            True if successful
        """
        try:
            logger.info("🌍 Initializing genesis file...")
            
            genesis_file = os.path.join(self.config.config_dir, 'genesis.json')
            
            if genesis_url:
                # Download genesis file
                logger.info(f"📥 Downloading genesis from {genesis_url}...")
                response = requests.get(genesis_url, timeout=60)
                response.raise_for_status()
                
                with open(genesis_file, 'w') as f:
                    f.write(response.text)
                
                logger.info(f"✅ Genesis file downloaded to {genesis_file}")
            else:
                # Use default genesis (already created by init)
                if os.path.exists(genesis_file):
                    logger.info(f"✅ Genesis file exists at {genesis_file}")
                else:
                    logger.warning("⚠️  Genesis file not found, using default")
            
            # Validate genesis
            with open(genesis_file, 'r') as f:
                genesis_data = json.load(f)
                chain_id = genesis_data.get('chain_id', '')
                logger.info(f"✅ Genesis validated - Chain ID: {chain_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize genesis: {e}")
            return False
    
    def validate_node_binary(self) -> bool:
        """
        Validate QIE node binary
        
        Returns:
            True if valid
        """
        try:
            if not os.path.exists(self.config.qied_binary):
                logger.error(f"❌ Binary not found: {self.config.qied_binary}")
                return False
            
            result = subprocess.run(
                [self.config.qied_binary, 'version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                version = result.stdout.strip()
                logger.info(f"✅ Binary validated: {version}")
                return True
            else:
                logger.error(f"❌ Binary validation failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Binary validation error: {e}")
            return False
    
    def check_configuration_syntax(self) -> bool:
        """
        Check configuration file syntax
        
        Returns:
            True if valid
        """
        try:
            config_file = os.path.join(self.config.config_dir, 'config.toml')
            app_config_file = os.path.join(self.config.config_dir, 'app.toml')
            genesis_file = os.path.join(self.config.config_dir, 'genesis.json')
            
            issues = []
            
            # Check config.toml
            if not os.path.exists(config_file):
                issues.append(f"❌ config.toml not found at {config_file}")
            else:
                logger.info("✅ config.toml exists")
            
            # Check app.toml
            if not os.path.exists(app_config_file):
                issues.append(f"❌ app.toml not found at {app_config_file}")
            else:
                logger.info("✅ app.toml exists")
            
            # Check genesis.json
            if not os.path.exists(genesis_file):
                issues.append(f"❌ genesis.json not found at {genesis_file}")
            else:
                try:
                    with open(genesis_file, 'r') as f:
                        json.load(f)
                    logger.info("✅ genesis.json valid JSON")
                except json.JSONDecodeError as e:
                    issues.append(f"❌ genesis.json invalid: {e}")
            
            if issues:
                for issue in issues:
                    logger.error(issue)
                return False
            
            logger.info("✅ Configuration syntax validated")
            return True
            
        except Exception as e:
            logger.error(f"❌ Configuration validation error: {e}")
            return False
    
    def initialize_node_state(self) -> bool:
        """
        Initialize node state (unsafe-reset-all)
        
        Returns:
            True if successful
        """
        try:
            logger.info("🔄 Initializing node state...")
            
            result = subprocess.run(
                [
                    self.config.qied_binary,
                    'tendermint',
                    'unsafe-reset-all',
                    '--home', self.config.qie_home
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info("✅ Node state initialized")
                return True
            else:
                logger.error(f"❌ Node state initialization failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Node state initialization error: {e}")
            return False
    
    def print_setup_summary(self):
        """Print setup summary and next steps"""
        print("\n" + "="*60)
        print("🎉 QIE Node Setup Summary")
        print("="*60)
        print(f"Moniker:         {self.config.moniker}")
        print(f"Chain ID:        {self.config.chain_id}")
        print(f"Home Directory:  {self.config.qie_home}")
        print(f"Binary:          {self.config.qied_binary}")
        print(f"RPC Endpoint:    {self.config.rpc_endpoint}")
        print(f"API Endpoint:    {self.config.api_endpoint}")
        print(f"P2P Port:        {self.config.p2p_port}")
        print(f"gRPC Port:       {self.config.grpc_port}")
        print("="*60)
        print("\n📋 Next Steps:")
        print("1. Start the node:")
        print(f"   {self.config.qied_binary} start --home {self.config.qie_home}")
        print("\n2. Create a wallet:")
        print(f"   {self.config.qied_binary} keys add validator --home {self.config.qie_home}")
        print("\n3. Get testnet coins:")
        print("   Visit: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/7.-get-some-qie-coins")
        print("\n4. Register as validator:")
        print("   See: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/8.-register-your-validator")
        print("="*60 + "\n")
    
    def generate_dockerfile(self, output_path: Optional[str] = None) -> bool:
        """
        Generate Dockerfile for QIE node
        
        Args:
            output_path: Path to save Dockerfile (default: ./Dockerfile.qie)
            
        Returns:
            True if successful
        """
        try:
            if output_path is None:
                output_path = os.path.join(os.getcwd(), 'Dockerfile.qie')
            
            dockerfile_content = f"""# QIE Node Dockerfile
FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \\
    curl \\
    jq \\
    wget \\
    ca-certificates \\
    && rm -rf /var/lib/apt/lists/*

# Create qie user
RUN useradd -m -s /bin/bash qie

# Copy binary
COPY {os.path.basename(self.config.qied_binary)} /usr/local/bin/qied
RUN chmod +x /usr/local/bin/qied

# Set working directory
WORKDIR /home/qie
USER qie

# Create directories
RUN mkdir -p {self.config.qie_home}/config \\
    {self.config.qie_home}/data \\
    {self.config.qie_home}/logs

# Expose ports
EXPOSE {self.config.rpc_port} {self.config.p2p_port} {self.config.grpc_port} {self.config.api_port}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \\
    CMD curl -f http://localhost:{self.config.rpc_port}/health || exit 1

# Start node
CMD ["qied", "start", "--home", "{self.config.qie_home}"]
"""
            
            with open(output_path, 'w') as f:
                f.write(dockerfile_content)
            
            logger.info(f"✅ Dockerfile generated: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to generate Dockerfile: {e}")
            return False
    
    def generate_docker_compose(self, output_path: Optional[str] = None) -> bool:
        """
        Generate docker-compose.yml for QIE node
        
        Args:
            output_path: Path to save docker-compose.yml
            
        Returns:
            True if successful
        """
        try:
            if output_path is None:
                output_path = os.path.join(os.getcwd(), 'docker-compose.qie.yml')
            
            compose_content = f"""version: '3.8'

services:
  qie-node:
    build:
      context: .
      dockerfile: Dockerfile.qie
    container_name: {self.config.moniker}
    ports:
      - "{self.config.rpc_port}:{self.config.rpc_port}"
      - "{self.config.p2p_port}:{self.config.p2p_port}"
      - "{self.config.grpc_port}:{self.config.grpc_port}"
      - "{self.config.api_port}:{self.config.api_port}"
    volumes:
      - qie-data:{self.config.qie_home}
      - ./config:{self.config.config_dir}
      - ./logs:{self.config.logs_dir}
    environment:
      - CHAIN_ID={self.config.chain_id}
      - MONIKER={self.config.moniker}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:{self.config.rpc_port}/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

volumes:
  qie-data:
    driver: local
"""
            
            with open(output_path, 'w') as f:
                f.write(compose_content)
            
            logger.info(f"✅ Docker Compose file generated: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to generate docker-compose.yml: {e}")
            return False
    
    def get_node_status(self) -> Dict[str, Any]:
        """
        Get node status
        
        Returns:
            Node status information
        """
        try:
            result = subprocess.run(
                [self.config.qied_binary, 'status', '--home', self.config.qie_home],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                status = json.loads(result.stdout)
                return {
                    'status': 'running',
                    'data': status
                }
            else:
                return {
                    'status': 'stopped',
                    'error': result.stderr
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def check_sync_progress(self) -> Dict[str, Any]:
        """
        Check block synchronization progress
        
        Returns:
            Sync progress information
        """
        try:
            response = requests.get(
                f"{self.config.rpc_endpoint}/status",
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            sync_info = data.get('result', {}).get('sync_info', {})
            
            return {
                'catching_up': sync_info.get('catching_up', False),
                'latest_block_height': sync_info.get('latest_block_height', '0'),
                'latest_block_time': sync_info.get('latest_block_time', ''),
                'synced': not sync_info.get('catching_up', True)
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to check sync progress: {e}")
            return {
                'error': str(e)
            }
    
    def check_network_connectivity(self) -> Dict[str, Any]:
        """
        Check network connectivity
        
        Returns:
            Network connectivity information
        """
        try:
            response = requests.get(
                f"{self.config.rpc_endpoint}/net_info",
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            result = data.get('result', {})
            
            return {
                'listening': result.get('listening', False),
                'n_peers': len(result.get('peers', [])),
                'peers': result.get('peers', [])
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to check network connectivity: {e}")
            return {
                'error': str(e)
            }
    
    def get_resource_usage(self) -> Dict[str, Any]:
        """
        Get resource usage (CPU, memory, disk)
        
        Returns:
            Resource usage information
        """
        try:
            return {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory': {
                    'total_gb': round(psutil.virtual_memory().total / (1024**3), 2),
                    'used_gb': round(psutil.virtual_memory().used / (1024**3), 2),
                    'available_gb': round(psutil.virtual_memory().available / (1024**3), 2),
                    'percent': psutil.virtual_memory().percent
                },
                'disk': {
                    'total_gb': round(psutil.disk_usage('/').total / (1024**3), 2),
                    'used_gb': round(psutil.disk_usage('/').used / (1024**3), 2),
                    'free_gb': round(psutil.disk_usage('/').free / (1024**3), 2),
                    'percent': psutil.disk_usage('/').percent
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get resource usage: {e}")
            return {
                'error': str(e)
            }
    
    def print_documentation(self):
        """Print setup instructions and documentation links"""
        print("\n" + "="*60)
        print("📚 QIE Node Documentation")
        print("="*60)
        print("\n🔗 Official Documentation:")
        print("   - Main Guide: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3")
        print("   - Install Node: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/2.-install-qie-node")
        print("   - Register Validator: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/8.-register-your-validator")
        print("   - Verify Validator: https://docs.qie.digital/how-to-become-a-validator-on-qie-v3/9.-verify-your-validator")
        print("\n📖 Quick Commands:")
        print(f"   - Start Node:      {self.config.qied_binary} start --home {self.config.qie_home}")
        print(f"   - Check Status:    {self.config.qied_binary} status --home {self.config.qie_home}")
        print(f"   - Create Wallet:   {self.config.qied_binary} keys add validator --home {self.config.qie_home}")
        print(f"   - List Wallets:    {self.config.qied_binary} keys list --home {self.config.qie_home}")
        print(f"   - Check Balance:   {self.config.qied_binary} query bank balances <address> --home {self.config.qie_home}")
        print("="*60 + "\n")
    
    def run_full_setup(self) -> bool:
        """
        Run complete node setup process
        
        Returns:
            True if successful
        """
        print("\n" + "="*60)
        print("🚀 Starting QIE Node Complete Setup")
        print("="*60 + "\n")
        
        # Step 1: Validate system requirements
        print("📋 Step 1/6: Validating system requirements...")
        is_valid, issues = self.validate_system_requirements()
        if not is_valid:
            logger.error("❌ Setup aborted due to system requirement failures")
            return False
        
        # Step 2: Download binary
        print("\n📥 Step 2/6: Downloading QIE binary...")
        if not self.download_qie_binary():
            logger.error("❌ Setup aborted: Binary download failed")
            return False
        
        # Step 3: Install node
        print("\n🔧 Step 3/6: Installing QIE node...")
        if not self.install_qie_node():
            logger.error("❌ Setup aborted: Node installation failed")
            return False
        
        # Step 4: Create configuration
        print("\n⚙️  Step 4/6: Creating node configuration...")
        if not self.create_node_config():
            logger.error("❌ Setup aborted: Configuration creation failed")
            return False
        
        # Step 5: Initialize genesis
        print("\n🌍 Step 5/6: Initializing genesis...")
        if not self.initialize_genesis():
            logger.error("❌ Setup aborted: Genesis initialization failed")
            return False
        
        # Step 6: Validate setup
        print("\n✅ Step 6/6: Validating setup...")
        if not self.validate_node_binary() or not self.check_configuration_syntax():
            logger.error("❌ Setup validation failed")
            return False
        
        # Print summary
        self.print_setup_summary()
        self.print_documentation()
        
        logger.info("🎉 QIE node setup completed successfully!")
        return True


def main():
    """Main entry point for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='QIE Node Setup and Configuration Manager'
    )
    
    parser.add_argument(
        'command',
        choices=[
            'setup', 'validate', 'download', 'install', 'config',
            'genesis', 'status', 'sync', 'network', 'resources',
            'docker', 'docs'
        ],
        help='Command to execute'
    )
    
    parser.add_argument('--moniker', help='Node moniker (default: valiguard-ai-validator)')
    parser.add_argument('--home', help='QIE home directory')
    parser.add_argument('--force', action='store_true', help='Force operation')
    
    args = parser.parse_args()
    
    # Create config
    config = NodeConfig()
    if args.moniker:
        config.moniker = args.moniker
    if args.home:
        config.qie_home = args.home
        config.config_dir = os.path.join(config.qie_home, 'config')
        config.data_dir = os.path.join(config.qie_home, 'data')
        config.logs_dir = os.path.join(config.qie_home, 'logs')
    
    # Create manager
    manager = QIESetupManager(config)
    
    # Execute command
    if args.command == 'setup':
        success = manager.run_full_setup()
        sys.exit(0 if success else 1)
    
    elif args.command == 'validate':
        is_valid, issues = manager.validate_system_requirements()
        sys.exit(0 if is_valid else 1)
    
    elif args.command == 'download':
        success = manager.download_qie_binary(force=args.force)
        sys.exit(0 if success else 1)
    
    elif args.command == 'install':
        success = manager.install_qie_node()
        sys.exit(0 if success else 1)
    
    elif args.command == 'config':
        success = manager.create_node_config()
        sys.exit(0 if success else 1)
    
    elif args.command == 'genesis':
        success = manager.initialize_genesis()
        sys.exit(0 if success else 1)
    
    elif args.command == 'status':
        status = manager.get_node_status()
        print(json.dumps(status, indent=2))
        sys.exit(0)
    
    elif args.command == 'sync':
        sync_info = manager.check_sync_progress()
        print(json.dumps(sync_info, indent=2))
        sys.exit(0)
    
    elif args.command == 'network':
        network_info = manager.check_network_connectivity()
        print(json.dumps(network_info, indent=2))
        sys.exit(0)
    
    elif args.command == 'resources':
        resources = manager.get_resource_usage()
        print(json.dumps(resources, indent=2))
        sys.exit(0)
    
    elif args.command == 'docker':
        manager.generate_dockerfile()
        manager.generate_docker_compose()
        print("✅ Docker files generated")
        sys.exit(0)
    
    elif args.command == 'docs':
        manager.print_documentation()
        sys.exit(0)


if __name__ == '__main__':
    main()
