"""Step 4: parse archived FDA drug-shortage detail pages into per-company supplier rows.

Reads data/raw/detail/{YYYY}/{timestamp}_{hash}.html (fetched by 02_fetch.py --only-needed). Each page has a
product header (status, date first posted) and one block per company: an <h3> heading
"Company ( Revised|New|Reverified mm/dd/yyyy )" followed by a content <div> holding either
  - a table: Presentation | Availability and Estimated Shortage Duration | Related Information | Shortage Reason
    (discontinuation pages: Presentation | Posting Date | Related Information), or
  - a "Presentation" list plus one "Note:" (resolved shortages), applied to every presentation.

Availability is normalized with a rule table (AVAIL_RULES) to available / disrupted / discontinued / unknown.
on_allocation flags "allocation" wording separately (counted as available; robustness can drop it).

Output: data/processed/suppliers.csv
  capture_date, capture_ts, ai_key, page_product, page_status, date_first_posted, company,
  company_update, company_update_date, presentation, availability_raw, related_info, shortage_reason,
  availability, on_allocation, parsed_by

Captures dated >= config.OOS_START are skipped unless --final is passed (holdout).

Usage: python src/04_parse_details.py [--final]
"""
import argparse
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

RAW = ROOT / "data" / "raw" / "detail"
PROC = ROOT / "data" / "processed"
# "Company ( Revised 05/15/2020 )"; labels seen: New, Revised, Reverified, Referified, Unable to Verify
HEAD_RE = re.compile(r"^(.*?)\s*\(\s*([A-Za-z ]+?)?\s*(\d{1,2}/\d{1,2}/\d{4})?\s*\)\s*$", re.S)

# First matching rule wins, so order matters: "not available" / "limited supply available" must be
# caught as disrupted before the plain "available" rule.
MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
AVAIL_RULES = [
    ("discontinued", r"discontinu|no longer (manufactur|market|availab)|no plans? to (manufactur|market)|"
                     r"exit(ed|ing)? the market|not (currently )?market|not commerciali|no longer distribut|"
                     r"do not distribute"),
    ("disrupted", r"not (currently )?available|unavailable|not avail|no (product|inventory|supply)|"
                  r"out of stock|backorder|back order|back-order|limited|intermittent|short supply|"
                  r"delay|constrain|on hold|insufficient|recall|temporar|next (release|delivery|shipment)|"
                  r"estimated (recovery|release|availability|resupply)|expected (release|recovery|availability)|"
                  r"release (date|expected)|resupply|depleted|until further notice|cannot meet|unable to|"
                  r"anticipated (availability|release|recovery)|expect(ed)? (stock|product|supply)|"
                  r"availability is (likely )?impacted|recovery is expected|interruption|"
                  r"recovery (is )?(projected|expected)|expect(ed)? full(y)? recovery|shortage anticipated|"
                  r"product expected|^(early|mid|late|end)[- ]+(q[1-4]|{MONTHS})|"
                  # future availability ("available by 4/5/19", "expects to have product available Q1 2015")
                  r"not yet|expects? to have|tentative|next available|expected to meet|will be available|expected to be available|date available|"
                  rf"available (by|after|beginning|starting|around|mid|early|late|end|week|month|q[1-4]|{MONTHS}|\d)|"
                  rf"^(availability:\s*)?(early|mid|late|end of)?[- ]?{MONTHS}\s*\d{{4}}\.?$|^q[1-4] \d{{4}}\.?$"),
    # Allocation without disruption wording: company is shipping to (some) customers -> available,
    # flagged on_allocation so robustness runs can drop it.
    ("available", r"available|in stock|meet(ing)? (full )?demand|no supply issue|shipping|released|"
                  r"releasing|normal (supply|production)|adequate|sufficient supply|has product|allocat"),
]
AVAIL_RES = [(label, re.compile(rx, re.I)) for label, rx in AVAIL_RULES]
ALLOC_RE = re.compile(r"allocat", re.I)


def classify(text: str) -> str:
    for label, rx in AVAIL_RES:
        if rx.search(text or ""):
            return label
    return "unknown"


def clean(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el is not None else ""


def file_index() -> dict:
    """data/raw/detail file name -> (timestamp, original URL), as named by 02_fetch.out_path."""
    idx = pd.read_csv(PROC / "index_detail.csv", dtype={"timestamp": str})
    return {f"{t}_{hashlib.sha1(o.encode()).hexdigest()[:12]}.html": (t, o)
            for t, o in zip(idx["timestamp"], idx["original"])}


def page_header(soup) -> dict:
    txt = clean(soup.body or soup)
    status = re.search(r"Status\s*:\s*(Currently in Shortage|Resolved|Discontinuation|To Be Discontinued)", txt, re.I)
    posted = re.search(r"Date first posted\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", txt, re.I)
    # Product name sits right before "Status:"
    prod = re.search(r"(?:Back to Previous Screen|Start Over)\s*(.*?)\s*Status\s*:", txt, re.I)
    return {
        "page_product": prod.group(1)[-200:] if prod else "",
        "page_status": status.group(1) if status else "",
        "date_first_posted": pd.to_datetime(posted.group(1), format="%m/%d/%Y").date() if posted else None,
    }


def company_blocks(soup):
    """Yield (heading text, content element) for each company <h3> that has a content block."""
    for h in soup.find_all("h3"):
        body = h.find_next_sibling()
        if body is None or not (body.find("table") or body.find(string=re.compile(r"Presentation"))):
            continue
        if body.find("h3"):  # container (2022+: the page-title <h3> wraps every company block) -> skip
            continue
        yield clean(h), body


def parse_block(body) -> list:
    """Rows of (presentation, availability_raw, related_info, shortage_reason) for one company block."""
    rows = []
    table = body.find("table")
    if table is not None:
        cols = [clean(th).lower() for th in table.find_all("th")]
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            cells = [clean(td) for td in tds]
            rec = dict(zip(cols, cells)) if len(cols) == len(cells) else {}
            pres = cells[0]
            if any(c.startswith("availability") for c in cols):       # shortage layout
                avail = next((v for k, v in rec.items() if k.startswith("availability")), cells[1] if len(cells) > 1 else "")
                related = rec.get("related information", cells[2] if len(cells) > 2 else "")
                reason = next((v for k, v in rec.items() if k.startswith("shortage reason")), cells[3] if len(cells) > 3 else "")
            else:                                                      # discontinuation layout
                related = rec.get("related information", cells[-1])
                avail, reason = related, ""
            rows.append((pres, avail, related, reason))
        return rows
    # List layout: <strong>Presentation</strong><ul>...</ul> <strong>Note:</strong><ul>...</ul>
    lists = {}
    for strong in body.find_all("strong"):
        ul = strong.find_next_sibling("ul")
        if ul is not None:
            lists[clean(strong).rstrip(":").lower()] = [clean(li) for li in ul.find_all("li")]
    note = " ".join(lists.get("note", []))
    for pres in lists.get("presentation", []) or [""]:
        rows.append((pres, note, "", ""))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="include holdout captures (single OOS run only)")
    args = ap.parse_args()

    spec = importlib.util.spec_from_file_location("parse_main", ROOT / "src" / "03_parse_main.py")
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)  # same AI= normalization as the main-page events
    names = file_index()

    out, pages, held_out = [], [], 0
    for f in sorted(RAW.rglob("*.html"), key=lambda f: f.name):  # data/raw/detail/{YYYY}/
        cap = pd.to_datetime(f.name[:8], format="%Y%m%d")
        if not args.final and cap >= pd.Timestamp(config.OOS_START):
            held_out += 1
            continue
        ts, original = names.get(f.name, (f.name.split("_")[0], ""))
        soup = BeautifulSoup(f.read_bytes(), "lxml")
        head = page_header(soup)
        n_rows, layout = 0, set()
        for heading, body in company_blocks(soup):
            m = HEAD_RE.match(heading)
            company, upd, upd_date = (m.group(1), m.group(2) or "", m.group(3)) if m else (heading, "", None)
            layout.add("table" if body.find("table") else "list")
            for pres, avail, related, reason in parse_block(body):
                out.append({
                    "capture_date": cap.date(), "capture_ts": ts, "ai_key": pm.ai_key(original) if original else "",
                    **head, "company": company.strip(), "company_update": upd,
                    "company_update_date": pd.to_datetime(upd_date, format="%m/%d/%Y").date() if upd_date else None,
                    "presentation": pres, "availability_raw": avail, "related_info": related,
                    "shortage_reason": reason,
                })
                n_rows += 1
        pages.append({"file": f.name, "capture_date": cap.date(), "page_status": head["page_status"],
                      "layout": "+".join(sorted(layout)) or "none", "rows": n_rows, "matched": bool(original)})

    if held_out:
        print(f"Skipped {held_out} captures dated >= {config.OOS_START} (holdout; use --final to include)")
    sup = pd.DataFrame(out)
    pg = pd.DataFrame(pages)
    # Discontinuation pages: every row is a discontinuation regardless of wording.
    disc_page = sup["page_status"].str.contains("Discontinu", case=False)
    sup["availability"] = sup["availability_raw"].map(classify)
    sup.loc[disc_page, "availability"] = "discontinued"
    sup["on_allocation"] = (sup["availability_raw"] + " " + sup["related_info"]).str.contains(ALLOC_RE)
    sup["parsed_by"] = "rule"
    sup.to_csv(PROC / "suppliers.csv", index=False)

    print(f"Pages: {len(pg)} | layouts: {pg['layout'].value_counts().to_dict()}")
    print(f"Page status: {pg['page_status'].replace('', '(none)').value_counts().to_dict()}")
    empty = pg[pg["rows"] == 0]
    print(f"Pages with no company rows: {len(empty)} "
          f"(status: {empty['page_status'].replace('', '(none)').value_counts().to_dict()})")
    if (~pg["matched"]).any():
        print(f"WARNING: {int((~pg['matched']).sum())} files not found in index_detail.csv (no ai_key)")
    print(f"\nRows -> {PROC / 'suppliers.csv'}: {len(sup):,} | companies: {sup['company'].nunique():,} "
          f"| pages with rows: {int((pg['rows'] > 0).sum())}")
    print(f"availability: {sup['availability'].value_counts().to_dict()} | on_allocation: {int(sup['on_allocation'].sum())}")
    unk = sup[sup["availability"] == "unknown"]
    if len(unk):
        print(f"\nunknown availability_raw (top 25 of {unk['availability_raw'].nunique()} distinct):")
        print(unk["availability_raw"].replace("", "(empty)").str[:110].value_counts().head(25).to_string())


if __name__ == "__main__":
    main()
