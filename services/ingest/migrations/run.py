"""
Migration runner for DeployLens.

Executes versioned SQL migration files in order against PostgreSQL.
Tracks applied versions in the schema_versions table.

Usage:
    python migrations/run.py                  # uses DATABASE_URL env var
    python migrations/run.py --url "postgres://..."
"""

import os
import sys
import glob
import argparse

import psycopg2


def get_connection(url: str):
    sync_url = url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
    return psycopg2.connect(sync_url)


def run_migrations(url: str):
    conn = get_connection(url)
    conn.autocommit = True
    cur = conn.cursor()

    migrations_dir = os.path.dirname(os.path.abspath(__file__))
    sql_files = sorted(glob.glob(os.path.join(migrations_dir, "V*.sql")))

    if not sql_files:
        print("No migration files found.")
        return

    for sql_path in sql_files:
        filename = os.path.basename(sql_path)
        version = filename.split("__")[0]

        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'schema_versions'
            )
        """)
        table_exists = cur.fetchone()[0]

        if table_exists:
            cur.execute("SELECT 1 FROM schema_versions WHERE version = %s", (version,))
            if cur.fetchone():
                print(f"  {filename} — already applied, skipping.")
                continue

        print(f"  {filename} — applying...")
        with open(sql_path, "r") as f:
            sql = f.read()
        cur.execute(sql)
        print(f"  {filename} — done.")

    cur.close()
    conn.close()
    print("\nAll migrations applied.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DeployLens migrations")
    parser.add_argument("--url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.url:
        print("Error: set DATABASE_URL or pass --url", file=sys.stderr)
        sys.exit(1)

    run_migrations(args.url)
