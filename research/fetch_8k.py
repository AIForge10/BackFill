"""Fetch earnings-announcement dates (8-K Item 2.02) from SEC EDGAR for the US tickers in the test.

SEC fair access requires a contact email in the User-Agent: set SEC_CONTACT_EMAIL (never committed).
Polite: well under SEC's 10 requests/second. Output: data/processed/earnings_8k.csv
(ticker, cik, filing_date, accepted, items, accession). Public SEC data.

Usage: SEC_CONTACT_EMAIL=you@example.com uv run python research/fetch_8k.py
"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
TICKERS = ["PFE", "TEVA", "BAX", "ICUI", "AMRX", "AMPH", "VTRS", "RDY"]


def get(session, url):
    time.sleep(0.25)
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def rows_from(block, ticker, cik):
    frame = pd.DataFrame({k: block.get(k, []) for k in ["form", "filingDate", "acceptanceDateTime", "items",
                                                         "accessionNumber"]})
    return frame.assign(ticker=ticker, cik=cik)


def main():
    email = os.environ.get("SEC_CONTACT_EMAIL")
    if not email:
        sys.exit("Set SEC_CONTACT_EMAIL (SEC fair-access policy requires a contact in the User-Agent).")
    session = requests.Session()
    session.headers["User-Agent"] = f"GatorQuantHacks Backfill research {email}"
    tickers = get(session, "https://www.sec.gov/files/company_tickers.json")
    cik = {v["ticker"]: int(v["cik_str"]) for v in tickers.values()}
    frames = []
    for t in TICKERS:
        if t not in cik:
            print(f"{t}: no CIK in SEC ticker map")
            continue
        c = cik[t]
        sub = get(session, f"https://data.sec.gov/submissions/CIK{c:010d}.json")
        frames.append(rows_from(sub["filings"]["recent"], t, c))
        for extra in sub["filings"].get("files", []):
            frames.append(rows_from(get(session, f"https://data.sec.gov/submissions/{extra['name']}"), t, c))
    allf = pd.concat(frames, ignore_index=True)
    earn = allf[(allf.form == "8-K") & allf["items"].fillna("").str.contains(r"\b2\.02\b")].copy()
    earn = earn.rename(columns={"filingDate": "filing_date", "acceptanceDateTime": "accepted",
                                "accessionNumber": "accession"})
    earn = earn[["ticker", "cik", "filing_date", "accepted", "items", "accession"]].sort_values(["ticker", "filing_date"])
    earn = earn[(earn.filing_date >= "2013-01-01") & (earn.filing_date < "2024-10-01")]  # in-sample only
    earn.to_csv(ROOT / "data/processed/earnings_8k.csv", index=False)
    print(earn.groupby("ticker").filing_date.agg(["count", "min", "max"]).to_string())
    forms = allf[allf.ticker.isin(["TEVA", "RDY"])].groupby(["ticker", "form"]).size()
    print("\nforeign-issuer check (6-K vs 8-K counts):", forms[forms.index.get_level_values(1).isin(["6-K", "8-K", "10-K", "20-F"])].to_dict())


if __name__ == "__main__":
    main()
