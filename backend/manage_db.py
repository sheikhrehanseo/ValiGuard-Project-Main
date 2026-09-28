#!/usr/bin/env python
"""
ValiGuard AI Database CLI Management Script

Usage:
    python backend/manage_db.py init          - Initialize database
    python backend/manage_db.py reset         - Reset database (drop and recreate)
    python backend/manage_db.py seed          - Seed with sample data
    python backend/manage_db.py export        - Export data to CSV
    python backend/manage_db.py backup        - Backup database
    python backend/manage_db.py health        - Check database health
    python backend/manage_db.py stats         - Show database statistics
    python backend/manage_db.py migrate       - Run pending migrations
"""

import sys
import argparse
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from database import (
    init_db_manager,
    get_db_manager,
    SeedData
)


def cmd_init(args):
    """Initialize database."""
    print("🔧 Initializing database...")
    db = get_db_manager()
    success = db.init_db()
    if success:
        print("✅ Database initialized successfully")
    else:
        print("❌ Database initialization failed")
        sys.exit(1)


def cmd_reset(args):
    """Reset database."""
    confirm = input("⚠️  This will delete all data. Type 'yes' to confirm: ")
    if confirm.lower() != "yes":
        print("❌ Reset cancelled")
        return
    
    print("🔄 Resetting database...")
    db = get_db_manager()
    success = db.reset_db(confirm=True)
    if success:
        print("✅ Database reset successfully")
    else:
        print("❌ Database reset failed")
        sys.exit(1)


def cmd_seed(args):
    """Seed database with sample data."""
    print("🌱 Seeding database with sample data...")
    db = get_db_manager()
    
    # Ensure database is initialized
    db.init_db()
    
    with db.get_session() as session:
        try:
            counts = SeedData.seed_all(session)
            print("\n✅ Sample data created:")
            for key, count in counts.items():
                print(f"   • {key.capitalize()}: {count}")
        except Exception as e:
            print(f"❌ Seeding failed: {e}")
            sys.exit(1)


def cmd_export(args):
    """Export data to CSV."""
    export_dir = args.dir if hasattr(args, 'dir') else "exports"
    print(f"📤 Exporting data to {export_dir}...")
    db = get_db_manager()
    
    success = db.export_to_csv(export_dir)
    if success:
        print(f"✅ Data exported successfully to {export_dir}")
    else:
        print("❌ Export failed")
        sys.exit(1)


def cmd_backup(args):
    """Backup database."""
    backup_dir = args.dir if hasattr(args, 'dir') else "backups"
    print(f"💾 Backing up database to {backup_dir}...")
    db = get_db_manager()
    
    backup_path = db.backup_db(backup_dir)
    if backup_path:
        print(f"✅ Database backed up to {backup_path}")
    else:
        print("❌ Backup failed")
        sys.exit(1)


def cmd_health(args):
    """Check database health."""
    print("🏥 Checking database health...\n")
    db = get_db_manager()
    
    health = db.health_check()
    
    print(f"Status: {health['status'].upper()}")
    print(f"Database: {health['database']}")
    print(f"Engine: {health['engine_type']}")
    print(f"Connection OK: {health['connection_ok']}")
    print(f"Tables: {health['tables']}")
    
    if health['status'] == 'unhealthy':
        print(f"Error: {health.get('error', 'Unknown error')}")
        sys.exit(1)
    else:
        print("✅ Database is healthy")


def cmd_stats(args):
    """Show database statistics."""
    print("📊 Database Statistics:\n")
    db = get_db_manager()
    
    stats = db.get_db_stats()
    if not stats:
        print("❌ Failed to retrieve statistics")
        sys.exit(1)
    
    print(f"Bridges: {stats.get('bridges', 0)}")
    print(f"Transactions: {stats.get('transactions', 0)}")
    print(f"  - Flagged: {stats.get('transactions_flagged', 0)}")
    print(f"Anomalies: {stats.get('anomalies', 0)}")
    print(f"Validators: {stats.get('validators', 0)}")
    print(f"Alerts: {stats.get('alerts', 0)}")
    print(f"  - Unresolved: {stats.get('alerts_unresolved', 0)}")


def cmd_migrate(args):
    """Run pending migrations."""
    print("🔄 Running database migrations...")
    db = get_db_manager()
    
    success = db.migrate_db()
    if success:
        print("✅ Migrations applied successfully")
    else:
        print("❌ Migration failed")
        sys.exit(1)


def main():
    """Main CLI handler."""
    parser = argparse.ArgumentParser(
        description="ValiGuard AI Database Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Init command
    subparsers.add_parser("init", help="Initialize database")
    
    # Reset command
    subparsers.add_parser("reset", help="Reset database (drop and recreate)")
    
    # Seed command
    subparsers.add_parser("seed", help="Seed database with sample data")
    
    # Export command
    export_parser = subparsers.add_parser("export", help="Export data to CSV")
    export_parser.add_argument("--dir", default="exports", help="Export directory")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Backup database")
    backup_parser.add_argument("--dir", default="backups", help="Backup directory")
    
    # Health command
    subparsers.add_parser("health", help="Check database health")
    
    # Stats command
    subparsers.add_parser("stats", help="Show database statistics")
    
    # Migrate command
    subparsers.add_parser("migrate", help="Run pending migrations")
    
    args = parser.parse_args()
    
    # Initialize database manager
    init_db_manager()
    
    # Command mapping
    commands = {
        "init": cmd_init,
        "reset": cmd_reset,
        "seed": cmd_seed,
        "export": cmd_export,
        "backup": cmd_backup,
        "health": cmd_health,
        "stats": cmd_stats,
        "migrate": cmd_migrate,
    }
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    if args.command not in commands:
        print(f"❌ Unknown command: {args.command}")
        parser.print_help()
        sys.exit(1)
    
    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
