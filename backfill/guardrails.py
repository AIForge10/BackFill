"""Append-only run records and a fail-closed holdout attempt lock."""
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def require_oos_freeze(root):
    head = git(root, "rev-parse", "HEAD")
    try:
        frozen = git(root, "rev-parse", "freeze-oos^{commit}")
    except subprocess.CalledProcessError as exc:
        raise ValueError("Holdout requires a freeze-oos git tag at the current commit.") from exc
    if frozen != head or git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Holdout requires freeze-oos at HEAD and a clean working tree.")
    return head


def fingerprint(root, paths, settings):
    files = {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
             for p in paths}
    return dict(commit=git(root, "rev-parse", "HEAD"), files=files, settings=settings.as_dict())


def reserve_holdout(path, identity):
    """Reserve before loading/evaluating returns. Any prior attempt blocks reuse.

    This intentionally has no retry override: failures must be reviewed outside
    the evaluation command; partial results cannot quietly reopen the holdout.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x") as f:
            json.dump(dict(status="started", started_at=datetime.now(timezone.utc).isoformat(),
                           identity=identity), f, indent=2)
            f.write("\n")
    except FileExistsError as exc:
        raise ValueError("Holdout already attempted; a partial or failed evaluation also stays locked.") from exc


def finish_holdout(path, status, detail):
    path = Path(path)
    record = json.loads(path.read_text())
    record.update(status=status, ended_at=datetime.now(timezone.utc).isoformat(), detail=detail)
    path.write_text(json.dumps(record, indent=2) + "\n")


def log_run(path, run_id, description, settings, events_file, symbols, status, *, summary=None, identity=None):
    """Preserve the existing sponsor CSV header; JSON in notes carries new fields."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    default = ["run_id", "date", "description", "events_file", "symbols", "hold_days", "cost_bp",
               "period", "total_return_pct", "sharpe", "max_drawdown_pct", "turnover", "notes"]
    if path.exists() and path.stat().st_size:
        with path.open(newline="") as f:
            fields = next(csv.reader(f))
    else:
        fields = default
    summary = summary or {}
    row = dict(run_id=run_id, date=datetime.now(timezone.utc).isoformat(), description=description,
               events_file=str(events_file), symbols=" ".join(sorted(symbols)), hold_days=settings.hold_days,
               cost_bp="country-specific", period=f"{settings.start} to {settings.end}",
               sharpe=summary.get("sharpe", ""), max_drawdown_pct=100 * summary["max_drawdown"]
               if "max_drawdown" in summary else "", turnover=summary.get("annualized_turnover", ""),
               notes=json.dumps(dict(status=status, is_final=settings.final, settings=settings.as_dict(),
                                     identity=identity, summary=summary), allow_nan=False))
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(row)
