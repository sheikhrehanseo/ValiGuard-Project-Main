import sqlite3
from pathlib import Path
import subprocess
import sys

db_file = Path(__file__).resolve().parents[1] / "valiguard.db"
print(f"Connecting to {db_file}...")
con = sqlite3.connect(str(db_file))
cursor = con.cursor()
tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Current tables:", tables)

cursor.execute("PRAGMA foreign_keys = OFF")
for table in tables:
    if table != "sqlite_sequence":
        print(f"Dropping table {table}...")
        cursor.execute(f"DROP TABLE IF EXISTS \"{table}\"")
con.commit()
cursor.execute("VACUUM")
con.commit()

remaining = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
con.close()
print("Remaining tables after drop & vacuum:", remaining)

print("Running Alembic migrations to recreate schema...")
backend_dir = Path(__file__).resolve().parents[1] / "backend"
res = subprocess.run(
    [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
    cwd=str(backend_dir),
    capture_output=True,
    text=True,
)
print("Alembic return code:", res.returncode)
print("Alembic output:", res.stdout)
if res.stderr:
    print("Alembic stderr:", res.stderr)
if res.returncode != 0:
    sys.exit(res.returncode)

con = sqlite3.connect(str(db_file))
new_tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("New tables in valiguard.db:", new_tables)
con.close()
print("Database successfully reset!")

