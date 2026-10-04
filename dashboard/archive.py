"""Wayback archive lookup for FDA drug-shortage detail pages.

One archive second can hold several drug pages, so a capture is identified by its timestamp
AND the drug named in the URL's AI= parameter. A timestamp-only lookup links to the wrong page.
"""
from urllib.parse import parse_qs, quote, urlsplit


def drug_key(text):
    """FDA URLs spell '%' as 'per' (AI=Dextrose+Monohydrate+10per+Injection)."""
    return " ".join(str(text).lower().replace("%", "per").split())


def archive_index(index_rows):
    """(timestamp, drug) -> original URL from data/processed/index_detail.csv rows."""
    result = {}
    for row in index_rows:
        drug = parse_qs(urlsplit(row["original"]).query).get("AI", [""])[0]
        if drug:
            result[(row["timestamp"], drug_key(drug))] = row["original"]
    return result


def wayback_url(index, timestamp, drug):
    """Exact archived page for this drug at this capture, or None (never a neighbouring page)."""
    original = index.get((timestamp, drug_key(drug)))
    return f"https://web.archive.org/web/{quote(timestamp, safe='')}/{original}" if original else None
