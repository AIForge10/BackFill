"""Step 3b: parse archived copies of the FDA "Download current drug shortages" CSV.

The FDA's list page went dark in the archive from Sep 2024 to Sep 2025 (the site moved to a JavaScript
app). Its CSV export (Drugshortages.cfm) kept being archived, so it fills that gap. Each copy is a
point-in-time snapshot: one row per company x presentation, with the FDA's Initial Posting Date.

Reads data/raw/csv/{capture_timestamp}.csv. Keeps only the columns the pipeline uses:
  generic name, company, presentation, availability, status, initial posting date,
  date/type of update, reason, therapeutic category, plus the capture timestamp.
Availability uses the same rule table as 04_parse_details.py; names use the same normalization as
03_parse_main.py (ai_key, coarse_key), so CSV rows join the existing tables.

Output: data/processed/fda_csv_rows.csv
Copies captured on/after config.OOS_START are skipped unless --final (holdout).

Usage: uv run python src/03b_parse_fda_csv.py [--final]
"""
import argparse
import importlib.util
import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

RAW = ROOT / "data" / "raw" / "csv"
OUT = ROOT / "data" / "processed" / "fda_csv_rows.csv"
COLUMNS = {  # FDA header (whitespace-stripped) -> our name
    "Generic Name": "generic_name", "Company Name": "company", "Presentation": "presentation",
    "Availability Information": "availability_raw", "Status": "status",
    "Initial Posting Date": "initial_posting_date", "Date of Update": "date_of_update",
    "Type of Update": "type_of_update", "Reason for Shortage": "reason", "Therapeutic Category": "category",
}
DATES = ["initial_posting_date", "date_of_update"]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_copy(path):
    """One archived CSV copy -> tidy rows. Decodes BOM/encodings; tolerates header whitespace."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    frame.columns = [c.strip() for c in frame.columns]
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {sorted(missing)}")
    frame = frame[list(COLUMNS)].rename(columns=COLUMNS)
    for c in frame:
        frame[c] = frame[c].str.strip()
    for c in DATES:
        frame[c] = pd.to_datetime(frame[c], format="%m/%d/%Y", errors="coerce")
    ts = path.stem
    frame.insert(0, "capture_ts", ts)
    frame.insert(1, "capture_date", pd.to_datetime(ts[:8], format="%Y%m%d"))
    return frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="include holdout copies (single OOS run only)")
    args = ap.parse_args()
    parse_main = _module("parse_main", "src/03_parse_main.py")
    details = _module("parse_details", "src/04_parse_details.py")

    frames, held_out = [], 0
    for path in sorted(RAW.glob("*.csv")):
        if not args.final and pd.Timestamp(path.stem[:8]) >= pd.Timestamp(config.OOS_START):
            held_out += 1
            continue
        frames.append(read_copy(path))
    if held_out:
        print(f"Skipped {held_out} copies captured >= {config.OOS_START} (holdout; use --final to include)")
    if not frames:
        raise SystemExit("No CSV copies to parse.")
    rows = pd.concat(frames, ignore_index=True)
    rows = rows[rows.generic_name != ""]
    rows["ai_key"] = rows.generic_name.map(parse_main.norm_ai)
    rows["coarse_key"] = rows.ai_key.map(parse_main.coarse_key)
    rows["availability"] = rows.availability_raw.map(details.classify)
    rows.loc[rows.status.str.contains("discontinu", case=False), "availability"] = "discontinued"
    rows["on_allocation"] = rows.availability_raw.str.contains(details.ALLOC_RE)
    future = rows.date_of_update > rows.capture_date + pd.Timedelta(days=1)
    if future.any():  # an update dated after the capture would be lookahead: drop and report
        print(f"Dropped {int(future.sum())} rows whose Date of Update is after their capture date")
        rows = rows[~future]
    rows.to_csv(OUT, index=False, date_format="%Y-%m-%d")

    print(f"Copies parsed: {rows.capture_ts.nunique()} ({rows.capture_date.min().date()} to {rows.capture_date.max().date()})")
    print(f"Rows -> {OUT}: {len(rows):,} | drugs: {rows.ai_key.nunique():,} | companies: {rows.company.nunique():,}")
    print("status:", rows.status.value_counts().to_dict())
    print("availability:", rows.availability.value_counts().to_dict())
    print("missing initial posting date:", int(rows.initial_posting_date.isna().sum()))


if __name__ == "__main__":
    main()
