"""Step 3: parse archived FDA Drug Shortages main pages into a status panel and shortage events.

Reads data/raw/main/{YYYY}/{timestamp}.html. Each page has two lists we use:
  - status table: Current / Resolved shortages (first table with st=c or st=r detail links)
  - discontinuations table (first other table with st=d detail links)
The therapeutic-category tabs repeat the same products and are never parsed.

Outputs:
  data/processed/main_status.csv      snapshot_date, product, ai_key, coarse_key, status, st, detail_url
  data/processed/shortage_events.csv  event_id, product, ai_key, coarse_key, public_date, prev_snapshot_gap_days,
                                      date_uncertain, left_censored, rename_window, spike_week,
                                      rename_suspect, rename_match, resolved_date

Events are detected on coarse_key (ingredient level, survives renames); each event has one row per
ai_key showing Current on its public_date, so ai_key stays usable for detail-page matching.
rename_window, spike_week and rename_suspect flag events excluded from the primary test (robustness only).

Snapshots dated >= config.OOS_START are skipped unless --final is passed (holdout).

Usage: python src/03_parse_main.py [--final]
"""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, unquote_plus, urljoin

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

RAW = ROOT / "data" / "raw" / "main"
OUT = ROOT / "data" / "processed"
BASE = "https://www.accessdata.fda.gov/scripts/drugshortages/"
DETAIL_RE = re.compile(r"dsp_ActiveIngredientDetails\.cfm", re.I)
ST_RE = re.compile(r"[?&]st=(\w)", re.I)
AI_RE = re.compile(r"[?&]AI=(.*?)(?=&[A-Za-z_]+=|$)", re.I)  # value ends at the next &param=
STATUS_TEXT = {"currently in shortage": "Current", "resolved": "Resolved"}
ST_STATUS = {"c": "Current", "r": "Resolved", "d": "Discontinued"}
DATE_UNCERTAIN_DAYS = 14
TEST_RE = re.compile(r"^test\b", re.I)                     # FDA test records, e.g. "TEST ADD REASON SHORTAGE"
RENAME_WINDOW = ("2023-09-01", "2023-10-15")                # FDA renamed most products mid-Sep 2023
SPIKE_MULT, SPIKE_WINDOW, SPIKE_FLOOR = 3, 13, 4           # rate > 3x trailing 13-page median and >= 4/week


def ai_key(href: str) -> str:
    """Normalized AI= value: URL-decode, lowercase, '%' variants decoded, collapse spaces."""
    m = AI_RE.search(href)
    raw = m.group(1) if m else ""
    # Older links hold plain text with spaces ('+' would be literal); newer ones are form-encoded.
    s = unquote(raw) if " " in raw else unquote_plus(raw)
    return norm_ai(s)


def norm_ai(s: str) -> str:
    """Shared by main and detail pages: lowercase, '%' variants -> '%', collapse spaces."""
    s = s.lower().strip()
    s = s.replace("chr(37)", "%").replace("%25", "%")      # ColdFusion / double-encoded percent signs
    s = re.sub(r"(?<=[\d.])per(cent)?|(?<=\d) per\b", "%", s)  # after a digit/point: keeps 'perphenazine'
    return re.sub(r"\s+", " ", s)


# Dosage-form / route / packaging words dropped from coarse_key (singular forms; plurals are singularized first).
FORM_WORDS = {
    "tablet", "capsule", "caplet", "injection", "injectable", "infusion", "oral", "orally", "solution",
    "suspension", "extended", "release", "delayed", "sustained", "controlled", "er", "xr", "sr", "dr", "odt",
    "for", "film", "coated", "chewable", "disintegrating", "dispersible", "effervescent", "powder",
    "lyophilized", "reconstitution", "concentrate", "emulsion", "liquid", "syrup", "elixir", "drop",
    "cream", "ointment", "gel", "lotion", "foam", "suppository", "enema", "rectal", "vaginal",
    "inhalation", "inhaler", "aerosol", "metered", "spray", "nasal", "ophthalmic", "otic", "topical",
    "transdermal", "patch", "intravenous", "iv", "intramuscular", "subcutaneous", "intrathecal", "sterile",
    "premix", "premixed", "vial", "ampule", "syringe", "prefilled", "kit", "bag", "irrigation",
    "preservative", "free", "single", "dose", "usp", "eq", "base", "in", "with", "and",
    "anhydrous", "monohydrate", "dihydrate", "trihydrate",  # hydrate forms (2023 names add these)
    "immediate", "synthetic", "strip", "inhalational", "forming",
    # package-level listings (e.g. 2024-04-14)
    "multidose", "novaplus", "premierpro", "bottle", "carton", "bulk", "package", "pharmacy", "pack", "ndc",
}
UNIT_WORDS = {"mg", "mcg", "ml", "meq", "mmol", "iu", "unit", "%"}
PACKAGE_RE = re.compile(r"\b(ndc|vial|bottle|carton|multidose|single-dose|novaplus|premierpro|kit|pack|"
                        r"bulk package|pharmacy bulk)\b|\d+-\d+")
CODE_RE = re.compile(r"\b\d+(-\d+)+\b")  # NDC / package codes
STRENGTH_RE = re.compile(r"\d[\d.,]*\s*(%|mg|mcg|g|ml|l|meq|mmol|units?|iu)?(\s*/\s*[\d.]*\s*(ml|l|g|mg|hr|h))?\b")


def singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def coarse_key(ak: str) -> str:
    """Ingredient-level key, used ONLY for the 180-day absence test (survives FDA renames)."""
    s = ak.lower()
    head, sep, tail = s.partition(";")
    if sep and PACKAGE_RE.search(tail):   # "<drug>; multidose vial (ndc ...)" -> drug only
        s = head                          # (";" between ingredients of a combination is kept)
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)  # bracketed brand names
    s = CODE_RE.sub(" ", s)
    s = re.sub(r"[®™©]|â", " ", s)
    s = re.sub(r"\bl-cysteine\b", "cysteine", s)
    s = STRENGTH_RE.sub(" ", s)
    s = re.sub(r"[,;:/'\"\-.%]", " ", s)
    s = re.sub(r"\bhcl\b", "hydrochloride", s)
    words = [singular(w) for w in s.split()]
    words = [w for w in words if w not in FORM_WORDS and w not in UNIT_WORDS]
    return " ".join(words) or ak


def detect_layout(table) -> str:
    if table is None:
        return "none"
    cls = " ".join(table.get("class") or [])
    if table.get("id") in ("cont", "dis"):
        return "datatables"   # seen from 2019-10: id=cont / id=dis, class=display
    if "footable" in cls:
        return "footable"     # seen 2017-2019
    if "tablesorter" in cls:
        return "tablesorter"  # seen 2015
    return "unknown"


def find_table(soup, codes: set, exclude=None):
    for t in soup.find_all("table"):
        if t is exclude:
            continue
        for a in t.find_all("a", href=DETAIL_RE):
            m = ST_RE.search(a["href"])
            if m and m.group(1).lower() in codes:
                return t
    return None


def parse_rows(table, snapshot_date, from_status_table: bool, warnings: list):
    rows = []
    for tr in table.find_all("tr"):
        a = tr.find("a", href=DETAIL_RE)
        if a is None:
            if tr.find("td"):
                warnings.append(f"{snapshot_date.date()}: row without detail link: {tr.get_text(' ', strip=True)[:60]!r}")
            continue
        href = a["href"]
        m = ST_RE.search(href)
        st = m.group(1).lower() if m else ""
        if from_status_table:
            text = tr.find_all("td")[-1].get_text(" ", strip=True).lower()
            status = STATUS_TEXT.get(text)
            if status is None:
                status = ST_STATUS.get(st)
                warnings.append(f"{snapshot_date.date()}: unknown status text {text!r}; used st={st!r} -> {status}")
            elif ST_STATUS.get(st) != status:
                warnings.append(f"{snapshot_date.date()}: status {status!r} disagrees with st={st!r} for {a.get_text(strip=True)!r}")
        else:
            status = "Discontinued"
        rows.append({
            "snapshot_date": snapshot_date,
            "product": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
            "ai_key": ai_key(href),
            "status": status,
            "st": st,
            "detail_url": urljoin(BASE, href),
        })
    return rows


def parse_all(final: bool):
    rows, pages, warnings = [], [], []
    n_test = 0
    files = sorted(RAW.rglob("*.html"), key=lambda f: f.name)  # data/raw/main/{YYYY}/
    held_out = 0
    for f in files:
        snapshot_date = pd.to_datetime(f.stem[:8], format="%Y%m%d")
        if not final and snapshot_date >= pd.Timestamp(config.OOS_START):
            held_out += 1
            continue
        soup = BeautifulSoup(f.read_bytes(), "lxml")
        status_t = find_table(soup, {"c", "r"})
        disc_t = find_table(soup, {"d"}, exclude=status_t)
        page_rows = []
        if status_t is not None:
            page_rows += parse_rows(status_t, snapshot_date, True, warnings)
        if disc_t is not None:
            page_rows += parse_rows(disc_t, snapshot_date, False, warnings)
        kept = [r for r in page_rows if not TEST_RE.match(r["product"])]
        n_test += len(page_rows) - len(kept)
        for r in kept:
            if not r["ai_key"]:
                warnings.append(f"{snapshot_date.date()}: dropped row with empty name/AI= ({r['status']})")
        kept = [r for r in kept if r["ai_key"]]
        page_rows = kept
        rows += page_rows
        n = pd.Series([r["status"] for r in page_rows], dtype=object).value_counts()
        pages.append({
            "file": f.name, "snapshot_date": snapshot_date,
            "layout": detect_layout(status_t), "disc_layout": detect_layout(disc_t),
            "current": int(n.get("Current", 0)), "resolved": int(n.get("Resolved", 0)),
            "discontinued": int(n.get("Discontinued", 0)),
            "ok": status_t is not None,
        })
    if held_out:
        print(f"Skipped {held_out} snapshots dated >= {config.OOS_START} (holdout; use --final to include)")
    print(f"Dropped {n_test} test-record rows (name matches ^test\\b)")
    status = pd.DataFrame(rows)
    status.insert(3, "coarse_key", status["ai_key"].map(coarse_key))
    return status, pd.DataFrame(pages), warnings


def spike_weeks(events: pd.DataFrame, snaps: pd.Series) -> set:
    """Snapshots whose new-event rate (events / weeks since the previous page) exceeds SPIKE_MULT x the
    trailing SPIKE_WINDOW-page median rate and is >= SPIKE_FLOOR. Backlogs after gaps are date_uncertain instead."""
    new = events[~events["left_censored"]].drop_duplicates("event_id")
    counts = new.groupby("public_date").size().reindex(snaps, fill_value=0)
    weeks = (snaps.diff().dt.days / 7).clip(lower=1).fillna(1).to_numpy()
    rate = counts / weeks
    base = rate.shift(1).rolling(SPIKE_WINDOW, min_periods=4).median()
    return set(rate.index[(rate > SPIKE_MULT * base) & (rate >= SPIKE_FLOOR)])


COMBO_RE = re.compile(r" and |\+|/|\bwith\b|;")


def is_combo(ai_keys) -> bool:
    """Combination product: any name has ' and ', '+', '/', 'with' or ';' once strengths (mg/ml) are removed."""
    return any(COMBO_RE.search(STRENGTH_RE.sub(" ", k)) for k in ai_keys)


def rename_suspects(ev: pd.DataFrame, status: pd.DataFrame) -> dict:
    """event_id -> earlier coarse_key whose word set is a subset/superset of the event's, Current in the prior
    NEW_SHORTAGE_GAP_DAYS. Combination products (either side) are never flagged."""
    named_current = status[status["status"] == "Current"]
    cur = named_current[["snapshot_date", "coarse_key"]].drop_duplicates()
    out = {}
    for _, e in ev[~ev["left_censored"]].drop_duplicates("event_id").iterrows():
        # A future rename/combination name cannot change today's eligibility.
        names = named_current[named_current["snapshot_date"] <= e["public_date"]].groupby("coarse_key")["ai_key"].agg(set)
        if is_combo(names[e["coarse_key"]]):
            continue
        w = set(e["coarse_key"].split())
        win = cur[(cur["snapshot_date"] < e["public_date"])
                  & (cur["snapshot_date"] >= e["public_date"] - pd.Timedelta(days=config.NEW_SHORTAGE_GAP_DAYS))]
        for ck in sorted(win["coarse_key"].unique()):
            v = set(ck.split())
            if ck != e["coarse_key"] and (w <= v or v <= w) and not is_combo(names[ck]):
                out[e["event_id"]] = ck
                break
    return out


def build_events(status: pd.DataFrame, snapshots: pd.Series) -> pd.DataFrame:
    """One event per coarse_key each time it shows Current after >= NEW_SHORTAGE_GAP_DAYS without Current."""
    snaps = pd.Series(sorted(snapshots.unique()))
    prev_snap = dict(zip(snaps.iloc[1:], snaps.iloc[:-1]))
    first_snap = snaps.iloc[0]
    cur = status[status["status"] == "Current"]
    resolved = status[status["status"] == "Resolved"]

    events, eid = [], 0
    for ck, g in cur.sort_values("snapshot_date").groupby("coarse_key"):
        dates = sorted(g["snapshot_date"].unique())
        starts = [0] + [i for i in range(1, len(dates))
                        if (dates[i] - dates[i - 1]).days >= config.NEW_SHORTAGE_GAP_DAYS]
        for j, i in enumerate(starts):
            d = dates[i]
            nxt = dates[starts[j + 1]] if j + 1 < len(starts) else pd.Timestamp.max
            gap = (d - prev_snap[d]).days if d in prev_snap else None
            eid += 1
            for _, r in g[g["snapshot_date"] == d].drop_duplicates("ai_key").iterrows():
                res = resolved.loc[(resolved["ai_key"] == r["ai_key"]) & (resolved["snapshot_date"] > d)
                                   & (resolved["snapshot_date"] < nxt), "snapshot_date"]
                events.append({
                    "event_id": eid,
                    "product": r["product"],
                    "ai_key": r["ai_key"],
                    "coarse_key": ck,
                    "public_date": d,
                    "prev_snapshot_gap_days": gap,
                    "date_uncertain": gap is not None and gap > DATE_UNCERTAIN_DAYS,
                    "left_censored": d == first_snap,
                    "resolved_date": res.min().date() if len(res) else None,
                })
    ev = pd.DataFrame(events)
    ev["rename_window"] = ev["public_date"].between(*map(pd.Timestamp, RENAME_WINDOW))
    ev["spike_week"] = ev["public_date"].isin(spike_weeks(ev, snaps))
    ev["rename_match"] = ev["event_id"].map(rename_suspects(ev, status))
    ev["rename_suspect"] = ev["rename_match"].notna()
    ev = ev.sort_values(["public_date", "coarse_key", "ai_key"]).reset_index(drop=True)
    ev["event_id"] = ev.groupby(["public_date", "coarse_key"], sort=True).ngroup() + 1  # number in date order
    ev["public_date"] = ev["public_date"].dt.date
    cols = ["event_id", "product", "ai_key", "coarse_key", "public_date", "prev_snapshot_gap_days",
            "date_uncertain", "left_censored", "rename_window", "spike_week", "rename_suspect", "rename_match",
            "resolved_date"]
    return ev[cols].astype({"prev_snapshot_gap_days": "Int64"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="include holdout snapshots (single OOS run only)")
    args = ap.parse_args()

    status, pages, warnings = parse_all(args.final)

    print("Products per snapshot:")
    print(pages[["snapshot_date", "layout", "disc_layout", "current", "resolved", "discontinued"]]
          .assign(snapshot_date=pages["snapshot_date"].dt.date).to_string(index=False))
    bad = pages[~pages["ok"]]
    if len(bad):
        print(f"\nWARNING: {len(bad)} pages with no status table found:\n{bad[['file', 'disc_layout']].to_string(index=False)}")
    unknown = pages[pages["ok"] & (pages["layout"] == "unknown")]
    if len(unknown):
        print(f"\nWARNING: {len(unknown)} pages parsed with an unrecognized layout: {unknown['file'].tolist()}")
    if warnings:
        print(f"\n{len(warnings)} row warnings:")
        print("\n".join(warnings))
    dup = status.duplicated(["snapshot_date", "ai_key", "status"])
    if dup.any():
        print(f"\nDropped {int(dup.sum())} duplicate (snapshot_date, ai_key, status) rows")
        status = status[~dup]

    merges = (status[status["status"] != "Discontinued"].groupby("coarse_key")["ai_key"]
              .agg(n_ai_keys="nunique", ai_keys=lambda s: " | ".join(sorted(s.unique()))))
    print(f"\ncoarse_key merges: {status['ai_key'].nunique():,} ai_keys -> {status['coarse_key'].nunique():,} coarse_keys "
          f"(current/resolved list: {merges['n_ai_keys'].sum():,} -> {len(merges):,})")
    big = merges[merges["n_ai_keys"] > 3].sort_values("n_ai_keys", ascending=False)
    print(f"coarse_keys with > 3 ai_keys: {len(big)}")
    for ck, r in big.iterrows():
        print(f"  [{r.n_ai_keys}] {ck}: {r.ai_keys[:300]}")

    status.assign(snapshot_date=status["snapshot_date"].dt.date).to_csv(OUT / "main_status.csv", index=False)
    events = build_events(status, pages.loc[pages["ok"], "snapshot_date"])
    events.to_csv(OUT / "shortage_events.csv", index=False)

    ev1 = events.drop_duplicates("event_id")
    new = ev1[~ev1["left_censored"]]
    print(f"\nSnapshots parsed: {pages['ok'].sum()} of {len(pages)} "
          f"({pages['snapshot_date'].min().date()} to {pages['snapshot_date'].max().date()})")
    print(f"Rows -> {OUT / 'main_status.csv'}: {len(status):,}")
    print(f"Events -> {OUT / 'shortage_events.csv'}: {len(events):,} rows, {len(ev1):,} events")
    print(f"  new events (not left-censored): {len(new):,}")
    print(f"  date_uncertain (gap > {DATE_UNCERTAIN_DAYS}d): {int(new['date_uncertain'].sum()):,}")
    print(f"  rename_window {RENAME_WINDOW}: {int(new['rename_window'].sum()):,}")
    print(f"  spike_week: {int(new['spike_week'].sum()):,}")
    print(f"  rename_suspect: {int(new['rename_suspect'].sum()):,}")
    primary = new[~new["rename_window"] & ~new["spike_week"] & ~new["rename_suspect"]]
    print(f"  primary (new, none of rename_window / spike_week / rename_suspect): {len(primary):,}")
    print(f"  left_censored (in first snapshot {pages.loc[pages['ok'], 'snapshot_date'].min().date()}): "
          f"{int(ev1['left_censored'].sum()):,}")
    print(f"  with resolved_date (any ai_key): "
          f"{events[~events['left_censored']].groupby('event_id')['resolved_date'].apply(lambda s: s.notna().any()).sum():,}")


if __name__ == "__main__":
    main()
