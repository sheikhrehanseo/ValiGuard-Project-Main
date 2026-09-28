"""
test_qie_node_manager.py
Test suite for the QIE Node Manager module.

Usage:
  python backend/test_qie_node_manager.py
"""

import json
import sys
from qie_node_manager import QIENodeManager


def test_manager_initialization():
    """Test that the manager initializes correctly."""
    print("\n[TEST] Manager Initialization")
    manager = QIENodeManager()
    print(f"  RPC URL: {manager.rpc_url}")
    print(f"  Chain ID: {manager.chain_id}")
    print(f"  Moniker: {manager.moniker}")
    print(f"  QIE Home: {manager.qie_home}")
    print("  ✓ Manager initialized successfully")
    return manager


def test_node_health(manager: QIENodeManager):
    """Test node health check."""
    print("\n[TEST] Node Health Check")
    health = manager.check_node_health()
    print(f"  Healthy: {health['healthy']}")
    print(f"  Message: {health['message']}")
    print(f"  Height: {health['height']}")
    print(f"  ✓ Health check completed: {json.dumps(health, indent=4)}")


def test_node_status(manager: QIENodeManager):
    """Test getting node status."""
    print("\n[TEST] Node Status")
    status = manager.get_node_status()
    print(f"  Online: {status['online']}")
    print(f"  Message: {status['message']}")
    if status['data']:
        print(f"  Status data (truncated): {json.dumps(status['data'], indent=4)[:200]}...")
    print(f"  ✓ Status retrieval completed")


def test_latest_block(manager: QIENodeManager):
    """Test getting latest block."""
    print("\n[TEST] Latest Block")
    block = manager.get_latest_block()
    print(f"  Found: {block['found']}")
    print(f"  Height: {block['height']}")
    print(f"  Message: {block['message']}")
    print(f"  ✓ Block retrieval completed")


def test_validator_info(manager: QIENodeManager):
    """Test getting validator info (will fail if validator doesn't exist, which is expected)."""
    print("\n[TEST] Validator Info")
    # Use a test address - will likely fail but tests error handling
    test_address = "qievaloper1example123"
    result = manager.get_validator_info(test_address)
    print(f"  Found: {result['found']}")
    print(f"  Message: {result['message']}")
    print(f"  ✓ Validator query completed (expected to fail for test address)")


def test_balance_query(manager: QIENodeManager):
    """Test balance query."""
    print("\n[TEST] Balance Query")
    # Use a test address - will likely return 0 or error, which is expected
    test_address = "qie1example123"
    balance = manager.query_balance(test_address)
    print(f"  Success: {balance['success']}")
    print(f"  Balance: {balance['balance']}")
    print(f"  Denom: {balance['denom']}")
    print(f"  Message: {balance['message']}")
    print(f"  ✓ Balance query completed")


def test_broadcast_transaction(manager: QIENodeManager):
    """Test transaction broadcast (with mock data)."""
    print("\n[TEST] Transaction Broadcast")
    mock_tx = {
        "type": "cosmos-sdk/StdTx",
        "value": {
            "msg": [],
            "fee": {"amount": [], "gas": "200000"},
            "signatures": [],
            "memo": "test"
        }
    }
    result = manager.broadcast_transaction(mock_tx)
    print(f"  Success: {result['success']}")
    print(f"  Hash: {result['hash']}")
    print(f"  Code: {result['code']}")
    print(f"  Message: {result['message']}")
    print(f"  ✓ Broadcast test completed (expected to fail for unsigned tx)")


def main():
    """Run all tests."""
    print("=" * 60)
    print("QIE Node Manager Test Suite")
    print("=" * 60)
    
    try:
        # Initialize manager
        manager = test_manager_initialization()
        
        # Run tests
        test_node_health(manager)
        test_node_status(manager)
        test_latest_block(manager)
        test_validator_info(manager)
        test_balance_query(manager)
        test_broadcast_transaction(manager)
        
        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)
        print("\nNotes:")
        print("- Some tests will fail if the node is not running")
        print("- Balance/validator queries expect specific addresses")
        print("- Broadcast test uses unsigned mock data (expected to fail)")
        print("\nTo run the full test suite with a live node:")
        print("  1. Start a QIE node: qied start --home ~/.qieMainnetNode")
        print("  2. Run this test: python backend/test_qie_node_manager.py")
        
        return 0
    except Exception as e:
        print(f"\n[ERROR] Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
