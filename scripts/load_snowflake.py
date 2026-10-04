"""Load the published research record into Snowflake, then freeze it with a zero-copy clone.

    uv sync --extra snowflake
    uv run python scripts/load_snowflake.py

Reads credentials only from the repo-root .env (SNOWFLAKE_ACCOUNT, USER, PASSWORD, ROLE,
WAREHOUSE, DATABASE, SCHEMA); nothing about them is printed. Replaces these tables in
<DATABASE>.<SCHEMA> (BACKFILL.RESEARCH):

    RUNS            results/backtest_report/summary.csv
    TRADES          the four published 20/5 trade cashflow files, tagged by vendor policy and costs
    CACHE_MANIFEST  data/processed/final_candidate/v1/price_manifest.json, one row per price file
    PROOF           proof/freeze-v1/receipt.json

then runs CREATE OR REPLACE DATABASE <DATABASE>_FREEZE_V1 CLONE <DATABASE> and prints row counts
for both side by side. Source files are only read, never changed.
"""
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/research/final_candidate_v1_20261004/20261004T045406Z_8db48a"
SOURCES = dict(
    runs=ROOT / "results/backtest_report/summary.csv",
    trades=[RUN / f"{policy}/delay20_hold5/costs{costs}/winners/trades.csv"
            for policy in ("reference_mix", "webull_only") for costs in (1, 2)],
    manifest=ROOT / "data/processed/final_candidate/v1/price_manifest.json",
    proof=ROOT / "proof/freeze-v1/receipt.json",
)
SETTINGS = ("ACCOUNT", "USER", "PASSWORD", "ROLE", "WAREHOUSE", "DATABASE", "SCHEMA")
TABLES = ("RUNS", "TRADES", "CACHE_MANIFEST", "PROOF")
# Read-only role used by the public dashboard (created once by an admin); see dashboard/README.md.
READER_ROLE = "BACKFILL_READER"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def number(value, kind=float):
    """Empty cells become NULL rather than zero."""
    return None if value in ("", None) else kind(float(value)) if kind is int else kind(value)


def relative(path):
    return str(Path(path).relative_to(ROOT))


# ---- rows built from the files (no Snowflake needed; tested offline) ----

def runs_rows():
    source = SOURCES["runs"]
    digest = sha256(source)
    return [(r["variant"], r["source"], r["bundle"], number(r["events"], int), number(r["positions"], int),
             number(r["total_return"]), number(r["annualized_return"]), number(r["annualized_volatility"]),
             number(r["sharpe"]), number(r["sharpe_costs_x2"]), number(r["max_drawdown"]), number(r["win_rate"]),
             number(r["avg_lot_return"]), number(r["placebo_sharpe"]), number(r["winner_p"]),
             number(r["winner_minus_placebo_p"]), relative(source), digest)
            for r in read_csv(source)]


def trades_rows():
    rows = []
    for path in SOURCES["trades"]:
        policy, costs = path.parts[-5], int(path.parts[-3].removeprefix("costs"))
        digest = sha256(path)
        rows += [(r["date"], r["lot_id"], number(r["event_id"], int), r["ticker"], r["country"], r["leg"], r["reason"],
                  number(r["units"]), number(r["usd_notional"]), number(r["cost"]), policy, costs, relative(path), digest)
                 for r in read_csv(path)]
    return rows


def manifest_rows():
    raw = SOURCES["manifest"].read_text()
    manifest = json.loads(raw)
    return [(symbol, entry["file"], entry["sha256"], entry.get("rows"), entry.get("vendor"), entry.get("actual_start"),
             entry.get("actual_end"), json.dumps(entry), raw, sha256(SOURCES["manifest"]))
            for symbol, entry in sorted(manifest["symbols"].items())]


def proof_rows():
    r = json.loads(SOURCES["proof"].read_text())
    return [(r["tag"], r["commit"], r["manifest_sha256"], r["signature"], r["timestamp_utc"], r["explorer"])]


DDL = dict(
    RUNS="""SPEC_NAME STRING, SOURCE STRING, BUNDLE STRING, EVENTS INTEGER, POSITIONS INTEGER,
            TOTAL_RETURN FLOAT, ANNUALIZED_RETURN FLOAT, ANNUALIZED_VOLATILITY FLOAT, SHARPE FLOAT,
            SHARPE_COSTS_X2 FLOAT, MAX_DRAWDOWN FLOAT, WIN_RATE FLOAT, AVG_LOT_RETURN FLOAT, PLACEBO_SHARPE FLOAT,
            WINNER_P FLOAT, WINNER_MINUS_PLACEBO_P FLOAT, SOURCE_FILE STRING, SOURCE_SHA256 STRING""",
    TRADES="""TRADE_DATE DATE, LOT_ID STRING, EVENT_ID INTEGER, TICKER STRING, COUNTRY STRING, LEG STRING,
              REASON STRING, UNITS FLOAT, USD_NOTIONAL FLOAT, COST FLOAT, VENDOR_POLICY STRING,
              COST_MULTIPLIER INTEGER, SOURCE_FILE STRING, SOURCE_SHA256 STRING""",
    CACHE_MANIFEST="""SYMBOL STRING, PATH STRING, SHA256 STRING, ROW_COUNT INTEGER, VENDOR STRING,
                      ACTUAL_START DATE, ACTUAL_END DATE, ENTRY VARIANT, MANIFEST VARIANT, MANIFEST_SHA256 STRING""",
    PROOF="""TAG STRING, COMMIT STRING, MANIFEST_SHA256 STRING, SIGNATURE STRING, TIMESTAMP_UTC TIMESTAMP_TZ,
             EXPLORER STRING""",
)
ROWS = dict(RUNS=runs_rows, TRADES=trades_rows, CACHE_MANIFEST=manifest_rows, PROOF=proof_rows)


# ---- Snowflake ----

def settings():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    values = {name: os.environ.get(f"SNOWFLAKE_{name}", "").strip() for name in SETTINGS}
    missing = [f"SNOWFLAKE_{name}" for name, value in values.items() if not value]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")
    return values


def ident(name):
    """Only plain identifiers from .env are accepted, so they can be placed in SQL safely."""
    if not name.replace("_", "").isalnum():
        raise SystemExit(f"Unsupported Snowflake identifier in .env: {name!r}")
    return name.upper()


def load(cursor, table):
    rows = ROWS[table]()
    cursor.execute(f"CREATE OR REPLACE TABLE {table} ({DDL[table]})")
    if table == "CACHE_MANIFEST":
        # VARIANT values cannot be bound directly; parse them from text in a SELECT.
        for row in rows:
            cursor.execute(f"INSERT INTO {table} SELECT %s, %s, %s, %s, %s, %s, %s, "
                           "PARSE_JSON(%s), PARSE_JSON(%s), %s", row)
    else:
        marks = ", ".join(["%s"] * len(rows[0]))
        cursor.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
    return len(rows)


def regrant_reader(cursor, clone, schema, role=READER_ROLE):
    """A replaced clone loses database-level grants; restore the dashboard's read-only access."""
    if not cursor.execute(f"SHOW ROLES LIKE '{role}'").fetchall():
        return
    for statement in (f"GRANT USAGE ON DATABASE {clone} TO ROLE {role}",
                      f"GRANT USAGE ON SCHEMA {clone}.{schema} TO ROLE {role}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {clone}.{schema} TO ROLE {role}"):
        cursor.execute(statement)
    print(f"re-granted read-only access on {clone} to {role}")


def count(cursor, database, schema, table):
    try:
        return cursor.execute(f"SELECT COUNT(*) FROM {database}.{schema}.{table}").fetchone()[0]
    except Exception:
        return None


def main():
    import snowflake.connector
    s = settings()
    database, schema = ident(s["DATABASE"]), ident(s["SCHEMA"])
    clone = f"{database}_FREEZE_V1"
    try:
        conn = snowflake.connector.connect(account=s["ACCOUNT"], user=s["USER"], password=s["PASSWORD"],
                                           role=s["ROLE"], warehouse=s["WAREHOUSE"], login_timeout=30)
    except Exception as exc:
        # Connector messages do not echo the password; print only the error class and message.
        raise SystemExit(f"Snowflake connection failed: {type(exc).__name__}: {exc}")
    with conn:
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {database}.{schema}")
        cursor.execute(f"USE SCHEMA {database}.{schema}")
        for table in TABLES:
            print(f"loaded {table:<15} {load(cursor, table):>4} rows")
        cursor.execute(f"CREATE OR REPLACE DATABASE {clone} CLONE {database}")
        print(f"cloned {database} -> {clone}")
        regrant_reader(cursor, clone, schema)
        print()
        print(f"{'TABLE':<16}{database + '.' + schema:>22}{clone + '.' + schema:>30}  MATCH")
        ok = True
        for table in TABLES:
            a, b = count(cursor, database, schema, table), count(cursor, clone, schema, table)
            ok &= a is not None and a == b
            print(f"{table:<16}{str(a):>22}{str(b):>30}  {'yes' if a == b and a is not None else 'NO'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
