"""Set up the ACESO database: migrations -> reference seed -> demo scenarios.

    python scripts/setup_db.py                 apply anything missing (safe to re-run)
    python scripts/setup_db.py --reseed-demo   rebuild the six demo patients' clinical data
    python scripts/setup_db.py --reset         DROP everything in the public schema first, then set up

Uses SUPABASE_DB_URL from .env, or the embedded local database if that is empty.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

import psycopg  # noqa: E402

from aceso.config import settings  # noqa: E402

MIGRATIONS = ROOT / "supabase" / "migrations"
SEED = ROOT / "supabase" / "seed.sql"

RESET_SQL = """
drop schema public cascade;
create schema public;
grant usage on schema public to postgres, anon, authenticated, service_role;
grant all on schema public to postgres, service_role;
alter default privileges in schema public grant all on tables to postgres, anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to postgres, anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to postgres, anon, authenticated, service_role;
"""


def for_local(sql: str) -> str:
    """The embedded local Postgres ships without pg_trgm and pgcrypto. Nothing at runtime
    needs trigram indexes, and scripts/local_shim.sql supplies the pgcrypto functions."""
    return "\n".join(line for line in sql.splitlines()
                     if "trgm" not in line and "extension if not exists pgcrypto" not in line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop and recreate the public schema first")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt for --reset")
    parser.add_argument("--reseed-demo", action="store_true", help="wipe and rebuild the demo patients' clinical data")
    parser.add_argument("--s1-labs-preloaded", action="store_true",
                        help="seed S1 with the lab report already uploaded (alert visible without a live upload)")
    parser.add_argument("--no-demo", action="store_true", help="skip the demo scenarios")
    args = parser.parse_args()

    url = settings.database_url()
    target = url.split("@")[-1]
    print(f"Database: {target}")
    with psycopg.connect(url, autocommit=True, prepare_threshold=None) as conn:
        has_trgm = conn.execute("select 1 from pg_available_extensions where name = 'pg_trgm'").fetchone()
        prepare = (lambda sql: sql) if has_trgm else for_local

        if args.reset:
            if not args.yes and input(f"This DELETES all ACESO tables and data in {target}. Type 'reset' to continue: ") != "reset":
                print("Aborted.")
                return 1
            conn.execute(RESET_SQL)
            conn.execute("drop table if exists supabase_migrations.schema_migrations")
            print("Public schema reset.")

        conn.execute("create schema if not exists supabase_migrations")
        conn.execute("create table if not exists supabase_migrations.schema_migrations "
                     "(version text primary key, statements text[], name text)")
        applied = {r[0] for r in conn.execute("select version from supabase_migrations.schema_migrations")}
        if not applied and conn.execute("select to_regclass('public.facts')").fetchone()[0]:
            print("\nThis database already has ACESO tables that were not created by this script,\n"
                  "so their exact state is unknown. Re-run with --reset to rebuild from scratch\n"
                  "(this deletes existing ACESO data).")
            return 1

        for path in sorted(MIGRATIONS.glob("*.sql")):
            version, _, name = path.stem.partition("_")
            if version in applied:
                continue
            with conn.transaction():
                conn.execute(prepare(path.read_text(encoding="utf-8")))
                conn.execute("insert into supabase_migrations.schema_migrations(version, name) values (%s, %s)",
                             (version, name))
            print(f"  applied {path.name}")

        with conn.transaction():
            conn.execute(SEED.read_text(encoding="utf-8"))
        print("Reference data, demo users and patients seeded.")

    if not args.no_demo:
        from aceso.db import close_pool
        from aceso.demo import seed_demo
        print("Demo scenarios (run through the real pipeline with a scripted model):")
        seed_demo(reseed=args.reseed_demo or args.reset, s1_labs_preloaded=args.s1_labs_preloaded)
        close_pool()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
