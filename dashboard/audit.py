"""Research audit: every tested variant, read from Snowflake with a file fallback.

/api/audit/variants  <DATABASE>.<SCHEMA>.RUNS (BACKFILL.RESEARCH), sorted by Sharpe
/api/audit/freeze    the same from the <DATABASE>_FREEZE_V1 clone, plus its PROOF row

Snowflake is queried at most once per endpoint every 10 minutes, never by the page. Missing
settings, a missing connector or any Snowflake error falls back to
results/backtest_report/summary.csv (and proof/freeze-v1/receipt.json) with source="file".
Never raises, and never returns connection settings or driver messages.
"""
import csv
import json
import os
import threading
import time
from pathlib import Path

CACHE_SECONDS = 600
SETTINGS = ("ACCOUNT", "USER", "PASSWORD", "ROLE", "WAREHOUSE", "DATABASE", "SCHEMA")
SUMMARY = "results/backtest_report/summary.csv"
RECEIPT = "proof/freeze-v1/receipt.json"
# The nine predeclared specifications in backfill/pipeline.py; anything else was chosen after seeing results.
REGISTERED = ("primary", "capture60", "allocation", "certain_dates", "all_flags",
              "hold20", "hold40", "hold120", "all_markets")
COLUMNS = ("SPEC_NAME", "SOURCE", "POSITIONS", "SHARPE", "SHARPE_COSTS_X2", "TOTAL_RETURN",
           "ANNUALIZED_RETURN", "MAX_DRAWDOWN", "WINNER_P", "WINNER_MINUS_PLACEBO_P")
PROOF_COLUMNS = ("TAG", "COMMIT", "MANIFEST_SHA256", "SIGNATURE", "TIMESTAMP_UTC", "EXPLORER")


def _number(value):
    try:
        return None if value in ("", None) else float(value)
    except (TypeError, ValueError):
        return None


def _variant(row):
    """One display record from a RUNS row or a summary.csv row (keys upper-cased)."""
    name = row.get("SPEC_NAME") or row.get("VARIANT")
    trades = _number(row.get("POSITIONS"))
    return dict(spec=name, origin=row.get("SOURCE"),
                label="registered" if name in REGISTERED else "chosen after seeing results",
                trades=None if trades is None else int(trades), sharpe=_number(row.get("SHARPE")),
                sharpe_x2=_number(row.get("SHARPE_COSTS_X2")), total_return=_number(row.get("TOTAL_RETURN")),
                annualized_return=_number(row.get("ANNUALIZED_RETURN")),
                max_drawdown=_number(row.get("MAX_DRAWDOWN")), winner_p=_number(row.get("WINNER_P")),
                winner_minus_placebo_p=_number(row.get("WINNER_MINUS_PLACEBO_P")))


def _sorted(rows):
    return sorted(rows, key=lambda r: (r["sharpe"] is None, -(r["sharpe"] or 0)))


def _ident(name):
    if not name or not name.replace("_", "").isalnum():
        raise ValueError("Unsupported Snowflake identifier")
    return name.upper()


class AuditService:
    def __init__(self, root, run_query=None, clock=time.monotonic, cache_seconds=CACHE_SECONDS, environ=os.environ):
        self.root = Path(root).resolve()
        self.run_query = run_query or self._snowflake_query
        self.clock = clock
        self.cache_seconds = cache_seconds
        self.environ = environ
        self._cache = {}
        self._lock = threading.Lock()

    # ---- public, cached ----

    def variants(self):
        return self._cached("variants", self._variants)

    def freeze(self):
        return self._cached("freeze", self._freeze)

    def _cached(self, key, compute):
        with self._lock:
            now = self.clock()
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.cache_seconds:
                return dict(hit[1], cached=True, age_seconds=round(now - hit[0]))
            result = compute()
            self._cache[key] = (now, result)
            return dict(result, cached=False, age_seconds=0)

    # ---- sources ----

    def _settings(self):
        values = {name: self.environ.get(f"SNOWFLAKE_{name}", "").strip() for name in SETTINGS}
        return values if all(values.values()) else None

    def _snowflake_query(self, settings, statements):
        """Run SELECTs on one short-lived connection; returns a list of row-dict lists."""
        import snowflake.connector
        conn = snowflake.connector.connect(account=settings["ACCOUNT"], user=settings["USER"],
                                           password=settings["PASSWORD"], role=settings["ROLE"],
                                           warehouse=settings["WAREHOUSE"], login_timeout=10, network_timeout=20)
        try:
            results = []
            for sql in statements:
                cursor = conn.cursor(snowflake.connector.DictCursor)
                try:
                    results.append(cursor.execute(sql).fetchall())
                finally:
                    cursor.close()
            return results
        finally:
            conn.close()

    def _from_snowflake(self, database_suffix="", with_proof=False):
        """(rows, proof, location) from Snowflake, or raises with a safe one-line reason."""
        settings = self._settings()
        if settings is None:
            raise LookupError("Snowflake is not configured in the server .env.")
        database, schema = _ident(settings["DATABASE"]) + database_suffix, _ident(settings["SCHEMA"])
        statements = [f"SELECT {', '.join(COLUMNS)} FROM {database}.{schema}.RUNS"]
        if with_proof:
            statements.append(f"SELECT {', '.join(PROOF_COLUMNS)} FROM {database}.{schema}.PROOF")
        try:
            results = self.run_query(settings, statements)
        except ImportError:
            raise LookupError("Snowflake connector not installed (uv sync --extra snowflake).")
        except Exception as exc:
            raise LookupError(f"Snowflake query failed ({type(exc).__name__}); showing the file copy.")
        rows = _sorted([_variant({k.upper(): v for k, v in r.items()}) for r in results[0]])
        proof = None
        if with_proof and results[1]:
            p = {k.upper(): v for k, v in results[1][0].items()}
            stamp = p.get("TIMESTAMP_UTC")
            proof = dict(tag=p.get("TAG"), commit=p.get("COMMIT"), manifest_sha256=p.get("MANIFEST_SHA256"),
                         signature=p.get("SIGNATURE"), explorer=p.get("EXPLORER"),
                         timestamp_utc=stamp.isoformat() if hasattr(stamp, "isoformat") else stamp)
        return rows, proof, f"{database}.{schema}"

    def _from_file(self):
        path = self.root / SUMMARY
        with path.open(newline="") as stream:
            rows = [_variant({k.upper(): v for k, v in r.items()}) for r in csv.DictReader(stream)]
        return _sorted(rows)

    def _file_proof(self):
        path = self.root / RECEIPT
        if not path.exists():
            return None
        r = json.loads(path.read_text())
        return {k: r.get(k) for k in ("tag", "commit", "manifest_sha256", "signature", "timestamp_utc", "explorer")}

    def _result(self, rows, source, location, reason, **extra):
        return dict(source=source, location=location, reason=reason, rows=rows,
                    registered=sum(r["label"] == "registered" for r in rows),
                    post_hoc=sum(r["label"] != "registered" for r in rows),
                    fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **extra)

    def _variants(self):
        try:
            rows, _, location = self._from_snowflake()
            return self._result(rows, "snowflake", f"{location}.RUNS", None)
        except Exception as exc:
            return self._fallback(exc)

    def _freeze(self):
        try:
            rows, proof, location = self._from_snowflake("_FREEZE_V1", with_proof=True)
            return self._result(rows, "snowflake", f"{location}.RUNS", None, snapshot=location.split(".")[0],
                                proof=proof, proof_source=f"{location}.PROOF")
        except Exception as exc:
            result = self._fallback(exc)
            return dict(result, snapshot=None, proof=self._file_proof(), proof_source=RECEIPT)

    def _fallback(self, exc):
        reason = str(exc) if isinstance(exc, LookupError) else "Snowflake unavailable; showing the file copy."
        try:
            rows = self._from_file()
        except Exception:
            return self._result([], "file", SUMMARY, reason + " The file copy could not be read either.")
        return self._result(rows, "file", SUMMARY, reason)
