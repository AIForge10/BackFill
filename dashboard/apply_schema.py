"""Operator command: apply dashboard/schema.sql with the writer connection (safe to re-run).

    uv run --extra dashboard python -m dashboard.apply_schema

Uses TIGER_INGEST_DATABASE_URL from the repo-root .env; the dashboard itself never runs this.
Every statement is idempotent (IF NOT EXISTS), so re-running only adds what is missing.
"""
import os
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    dsn = os.environ.get("TIGER_INGEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("Set TIGER_INGEST_DATABASE_URL in the repo-root .env.")
    import psycopg
    try:
        with psycopg.connect(dsn, connect_timeout=10, sslmode=os.environ.get("TIGER_SSLMODE", "require")) as conn:
            conn.execute(SCHEMA.read_text())
            columns = [r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='backfill_live' AND table_name='supplier_updates' ORDER BY ordinal_position")]
    except Exception:
        raise SystemExit("Schema could not be applied. Check the connection settings; credentials are not logged.") from None
    print(f"Schema applied. supplier_updates columns: {', '.join(columns)}")


if __name__ == "__main__":
    main()
