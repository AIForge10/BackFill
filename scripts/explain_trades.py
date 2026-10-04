"""Precompute plain-English trade summaries with Gemini and cache them for the dashboard.

    uv run python scripts/explain_trades.py --dry-run   # show the facts sent, no API call
    uv run python scripts/explain_trades.py             # writes results/explanations.json

Reads GEMINI_API_KEY (and optionally GEMINI_MODEL) only from the repo-root .env. For each trade in
the published 20/5 candidate (reference_mix, ordinary costs), only these structured facts are sent:
drug, notice date, entry date, exit date, ticker, net return and hedge. The dashboard serves the
cached text; it never calls Gemini. Nothing is written unless every trade gets a valid summary.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results/explanations.json"
DEFAULT_MODEL = "gemini-3.8-flash"
TRANSIENT = {403, 429, 500, 503}
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
INSTRUCTIONS = (
    "You summarize one completed historical backtest trade for a general reader. "
    "Write exactly 2 plain-English sentences using only the facts provided. "
    "Do not add any fact, number, date, cause, company detail or market context that is not given. "
    "Do not compute new numbers such as holding length. Write dates exactly as given (YYYY-MM-DD). "
    "Make no predictions and give no investment advice or recommendations. "
    "'hedge' is the ticker sold short to offset broad market moves. "
    "'net_return' is the trade's return after modeled costs. "
    "Use plain words, never the field names (write 'net return', not 'net_return'). "
    "The ticker's shares were bought (a long position); only the hedge was sold short. "
    "Never describe the ticker trade as short. Do not mention advice, predictions or these instructions."
)


def source_path():
    latest = json.loads((ROOT / "results/research/final_candidate_v1_20261004/latest.json").read_text())
    return ROOT / latest["directory"] / "reference_mix/delay20_hold5/costs1/winners/lots.csv"


def facts(row):
    return dict(drug=row["product"], notice_date=row["public_date"], entry_date=row["trade_date"],
                exit_date=row["exit_date"], ticker=row["ticker"],
                net_return=f"{float(row['net_lot_return']) * 100:.2f}%", hedge=row["hedge"])


def numbers(text):
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+(?:\.\d+)?", text)}


def check(text, given):
    """Reject output that is not two sentences, uses raw field names, or contains a number absent from the facts."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    if not text.strip().endswith((".", "!", "?")):
        raise ValueError("incomplete reply")
    if len(sentences) != 2:
        raise ValueError(f"expected 2 sentences, got {len(sentences)}")
    ticker, hedge = re.escape(given.get("ticker", "")), re.escape(given.get("hedge", ""))
    wrong_side = [r"\bshort (?:hedge )?trade\b", rf"\bshort(?:ed)? (?:position |trade )?(?:in |on )?(?:ticker )?{ticker}\b",
                  rf"\b{ticker} was (?:sold short|shorted)\b"] if ticker else []
    if any(re.search(pattern, text, re.I) for pattern in wrong_side):
        raise ValueError("describes the stock as a short position; only the hedge is short")
    if re.search(r"\b(?:advice|advise|recommend\w*|predict\w*|forecast\w*)\b", text, re.I):
        raise ValueError("mentions advice or predictions")
    field_names = sorted(set(re.findall(r"\b[a-z]+_[a-z_]+\b", text)))
    if field_names:
        raise ValueError(f"raw field names in reply: {field_names}")
    extra = numbers(text) - numbers(" ".join(given.values()))
    if extra:
        raise ValueError(f"numbers not in the facts: {sorted(extra)}")
    return text.strip()


def generate(session, key, model, given, waits=(5, 15, 30, 60, 60)):
    body = dict(systemInstruction=dict(parts=[dict(text=INSTRUCTIONS)]),
                contents=[dict(role="user", parts=[dict(text="Facts:\n" + json.dumps(given, indent=1))])],
                generationConfig=dict(temperature=0))
    for wait in (*waits, None):
        response = session.post(ENDPOINT.format(model=model), headers={"x-goog-api-key": key}, timeout=60, json=body)
        # Rate-limited tiers intermittently answer 403/429/5xx for the same valid request.
        if response.status_code not in TRANSIENT or wait is None:
            break
        print(f"  Gemini HTTP {response.status_code}; retrying in {wait}s", file=sys.stderr)
        time.sleep(wait)
    if response.status_code != 200:
        # Error bodies do not echo the key; report only the status.
        raise RuntimeError(f"Gemini returned HTTP {response.status_code}")
    body = response.json()
    candidate = body.get("candidates", [{}])[0]
    text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
    # A cut-off reply can still look like two sentences, so anything but a normal stop is discarded.
    return (text if candidate.get("finishReason") == "STOP" else ""), body.get("modelVersion", model)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--pause", type=float, default=4, help="seconds between calls, for free-tier rate limits")
    parser.add_argument("--only", nargs="+", metavar="TRADE_ID",
                        help="regenerate only these trades and merge them into the existing cache")
    args = parser.parse_args()
    source = source_path()
    with source.open(newline="") as stream:
        trades = {r["lot_id"]: facts(r) for r in csv.DictReader(stream)}
    if args.dry_run:
        print(json.dumps(trades, indent=1))
        return
    import requests
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("Missing in .env: GEMINI_API_KEY")
    model = args.model or os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    explanations, version, todo = {}, model, trades
    if args.only:
        unknown = sorted(set(args.only) - set(trades))
        if unknown:
            raise SystemExit(f"Unknown trade ids: {unknown}")
        cached = json.loads(OUTPUT.read_text())
        if cached.get("source_sha256") != hashlib.sha256(source.read_bytes()).hexdigest():
            raise SystemExit("The trades file changed since the cache was built; regenerate all trades.")
        if not cached.get("model", "").startswith(model.removeprefix("models/")):
            raise SystemExit(f"Cache was built with {cached.get('model')}; use the same model to merge.")
        explanations = {k: v for k, v in cached["explanations"].items() if k not in args.only}
        todo = {k: trades[k] for k in args.only}
    with requests.Session() as session:
        for trade_id, given in todo.items():
            for attempt in range(1, args.attempts + 1):
                time.sleep(args.pause)
                text, version = generate(session, key, model, given)
                try:
                    explanations[trade_id] = dict(text=check(text, given), facts=given)
                    break
                except ValueError as exc:
                    print(f"{trade_id}: attempt {attempt} rejected ({exc})", file=sys.stderr)
            else:
                raise SystemExit(f"{trade_id}: no valid summary after {args.attempts} attempts; nothing written")
            print(f"{trade_id}: {explanations[trade_id]['text']}")
    OUTPUT.write_text(json.dumps(dict(
        model=version, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=str(source.relative_to(ROOT)), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        instructions=INSTRUCTIONS, explanations=explanations), indent=1) + "\n")
    print(f"wrote {len(explanations)} summaries to {OUTPUT} ({version})")


if __name__ == "__main__":
    main()
