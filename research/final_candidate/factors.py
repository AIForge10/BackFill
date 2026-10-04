"""Convert separately acquired official factor ZIPs to a frozen IS-only CSV."""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_monthly(path, columns):
    with zipfile.ZipFile(path) as archive:
        content = archive.read(archive.namelist()[0]).decode("utf-8-sig")
    lines = [line for line in content.splitlines() if re.match(r"^\s*\d{6},", line)]
    data = pd.read_csv(io.StringIO("\n".join(lines)), header=None, names=["month", *columns])
    data.index = pd.to_datetime(data.pop("month").astype(str), format="%Y%m") + pd.offsets.MonthEnd(0)
    data = data.astype(float)
    if (data <= -99).any().any() or data.index.duplicated().any():
        raise ValueError("Missing or duplicate monthly factor observations.")
    return data / 100


def prepare():
    raw = ROOT / "data/raw/final_candidate_factors"
    source = json.loads((raw / "manifest.json").read_text())
    for entry in source.values():
        if sha(raw / entry["file"]) != entry["sha256"]:
            raise ValueError("Factor archive changed.")
    ff = parse_monthly(raw / source["F-F_Research_Data_Factors"]["file"], ["Mkt-RF", "SMB", "HML", "RF"])
    mom = parse_monthly(raw / source["F-F_Momentum_Factor"]["file"], ["Mom"])
    factors = ff.join(mom, how="inner").loc["2014-06-01":"2024-09-30", ["Mkt-RF", "HML", "Mom", "RF"]]
    expected = pd.date_range("2014-06-30", "2024-09-30", freq="ME")
    if not factors.index.equals(expected) or factors.isna().any().any():
        raise ValueError("Incomplete in-sample factors.")
    folder = ROOT / "data/processed/final_candidate/v1"
    target = folder / "factors.csv"
    if target.exists():
        raise ValueError("Frozen factors already prepared; no overwrite.")
    factors.to_csv(target, index_label="month")
    (folder / "factor_manifest.json").write_text(json.dumps(dict(
        sources=source, csv_sha256=sha(target), units="decimal monthly returns",
        start="2014-06-30", end="2024-09-30",
        note="Current CRSP CIZ factor vintage, acquired 2026-10-04; retrospective exposure check only, never a trading input."
    ), indent=2) + "\n")


if __name__ == "__main__":
    prepare()
