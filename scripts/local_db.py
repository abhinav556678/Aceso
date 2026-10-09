"""Start an embedded local Postgres (with pgvector) for offline work and demos.

    pip install pgserver
    python scripts/local_db.py        # keep this window open

The API and scripts/setup_db.py use it automatically while SUPABASE_DB_URL in
.env is empty. Data lives in .localdb/ ; delete that folder to start clean.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / ".localdb"


def start(data_dir: Path = DATA_DIR):
    try:
        import pgserver
    except ImportError:
        sys.exit("pgserver is not installed. Run: pip install pgserver")
    data_dir.mkdir(exist_ok=True)
    server = pgserver.get_server(data_dir / "pgdata", cleanup_mode="stop")
    # applied over a normal connection: pgserver's own psql helper breaks on paths with spaces
    import psycopg
    with psycopg.connect(server.get_uri(), autocommit=True) as conn:
        conn.execute((ROOT / "scripts" / "local_shim.sql").read_text(encoding="utf-8"))
    (data_dir / "url.txt").write_text(server.get_uri())
    return server


if __name__ == "__main__":
    server = start()
    print(f"Local Postgres running: {server.get_uri()}")
    print("Next, in another terminal: python scripts/setup_db.py")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("Stopping.")
