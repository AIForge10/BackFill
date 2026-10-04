# Backfill observatory

A small read-only dashboard built with the Rezt paper-and-instrument design.
Self-hosted Instrument Serif, Geist and Geist Mono; OS-driven dark mode;
dashed rails, node-marked sections, an integrity dial and accessible tables.
Historical numbers come from saved research artifacts. No backtest is run by
the UI, and no curve is invented from a reported summary.

## Start

From the repository root:

```bash
uv sync --extra dashboard
uv run python -m dashboard.server
```

Open **http://127.0.0.1:8080**. For the historical view without Tiger Data,
`python -m dashboard.server` works with Python 3.11+ and no additional packages.
Use `--port 8081` if necessary. `--data-root /path/to/Gator_Hacks` reads another
checkout's saved research records without changing them.

The default server binds to localhost. Put it behind your normal authenticated
reverse proxy before exposing database observations on a public deployment.

## What judges can inspect

- A short hypothesis explanation first, followed directly by an actual Webull
  daily-market chart. Select FMS/ICUI/SPY, line/bars, a preset or custom date range,
  series visibility and keyboard/hover inspection. Prices are indexed to 100 at
  November 11 (not dollar quotes), with right-side axes, a crosshair and actual
  announcement/entry/exit markers. No synthetic intraday ticks are inserted.
  The refined supplier rule and post-inspection status remain explicit.
- Three explicitly labeled strategies: the historical supplier primary,
  the exploratory strict-supplier delayed-entry candidate, and the reported
  exploratory specialist basket. The basket snapshot was exported from
  teammate commit `80c99b2`; exact price-cache replay is still pending.
- Standard/doubled costs and recorded-mix/Webull-only policies where outputs
  exist. Unavailable combinations show an explicit empty state.
- Actual saved strategy/control daily NAV, return/drawdown views, six reporting
  metrics, nominal uncertainty and profit concentration.
- Searchable/paginated frozen supplier ledger; event drawer with archive link,
  presentation evidence, supplier roles, information/entry/exit dates and lot
  cashflows. Controls are page-absent, not verified nonmanufacturers.
- Risk limits, lagged-ADV capacity, factor proxy exposure, vendor provenance,
  frozen-source hash checks and CSV/JSON downloads.
- The inspected 2024–2026 period is labeled as previously inspected. This
  dashboard makes no newly blind holdout claim.
- A separate Helene beneficiary case: expectation / saved-outcome reveal,
  actual session line/bar charts, source and date-range selectors, series
  toggles, keyboard/hover inspection, doubled costs, reconciled hedge waterfall
  and an illustrative capital slider. BAX has zero investment weight. All
  three previously inspected horizons are disclosed, including negative ones.

The November 11–18 case shows +1.06% saved net hedged return, distinct from
the −0.62% stock-only return and +1.15 percentage-point advantage over SPY.
These are returns on invested stock capital, not whole-account returns.
FMS's **saved accounting uses a Yahoo dividend-adjustment fallback**; ICUI and
SPY use Webull. The Webull-only price chart contains actual verified Webull
daily bars for all three instruments. It never substitutes mixed-vendor net
accounting into a Webull-only net view.

The strict later-period audit has 76 events and zero eligible trades; its
performance is unavailable. The case does not meet the frozen FDA availability
rule and is labeled an exploratory hypothetical illustration, not a successful
blind holdout. Revealing saved outcomes does not evaluate anything again.

`dashboard/data/helene_case.json` packages indexed price changes and saved
accounting, with source hashes. To refresh it from existing files only:

```bash
python -m dashboard.export_case --case-dir /path/to/saved_case --webull-cache /path/to/original_webull_cache --accounting-cache /path/to/recorded_accounting_cache
```

This verifies source price hashes and cashflow/curve reconciliation; it does
not fetch prices, launch an engine, change rules or consume a holdout attempt.
The capital slider scales the saved result linearly; it is not a new capacity
or market-impact estimate.

The default overview uses saved candidate outputs at
`results/research/final_candidate_v1_20261004/latest.json`. The original primary
and basket have summary metrics only here; missing curves are reported honestly.
Downloads expose selected derived artifacts, never credentials or licensed raw
price files. Filtering evidence does not select a new strategy or tune metrics.

## Proof on Solana

Section 07 shows the `freeze-v1` anchor from `proof/freeze-v1/receipt.json` and
`manifest.json`: anchor time, tag/commit, manifest hash, on-chain memo, explorer
link and the 10 fingerprinted files. **Verify now** calls `/api/proof/verify`,
which reuses `scripts/make_manifest.py` (recompute the memo from the git tag) and
`scripts/verify_proof.py` (read the memo live from Solana devnet) and returns:

- `PASS`: recomputed and on-chain memos match; both are shown side by side.
- `FAIL`: they differ, or devnet does not know the transaction; differing fields are named.
- `UNAVAILABLE`: devnet unreachable or the tag is not fetched (`git fetch --tags`);
  the saved receipt is shown instead. The endpoint never crashes the page.

Results are cached for 60 seconds per server process. `/api/proof` returns the
saved facts only and needs no network. The panel also separates the two integrity
checks: `freeze.json` (8 files, local copy against the team's recorded hashes, no
external timestamp) and `freeze-v1` (10 files, anchored on Solana). Four files are
in both. The proof shows the frozen rules existed at 2026-10-04 08:47 UTC; it does
not make the 2014–2024 backtest out-of-sample.

## Research audit (Snowflake)

Section 07's **Research audit** panel lists every tested specification: the nine
registered variants labeled `registered`, and the 20/5 candidate rows labeled
`chosen after seeing results`, sorted by Sharpe. It reads:

- `/api/audit/variants`: `BACKFILL.RESEARCH.RUNS`
- `/api/audit/freeze`: the zero-copy clone `BACKFILL_FREEZE_V1.RESEARCH.RUNS` plus its
  `PROOF` row (freeze-v1 manifest hash and Solana explorer link)

Load the tables first with `uv run --extra snowflake python scripts/load_snowflake.py`.
Credentials come only from the root `.env` (`SNOWFLAKE_*`). The server queries Snowflake
at most once per endpoint every 10 minutes; the page never polls it. If Snowflake is not
configured, the connector is missing (`uv sync --extra snowflake`) or a query fails, both
endpoints fall back to `results/backtest_report/summary.csv` (and the saved receipt) with
`source="file"`; driver messages and settings are never returned.

## AI trade summaries (Gemini, precomputed)

Each executed trade's evidence record shows a two-sentence summary labeled "AI-generated summary of
the facts above". The summaries are generated offline and cached; the page never calls Gemini.

```bash
uv run python scripts/explain_trades.py --dry-run   # print the facts that would be sent
uv run python scripts/explain_trades.py             # needs GEMINI_API_KEY in the root .env
```

For each lot in the published 20/5 candidate (`reference_mix/delay20_hold5/costs1/winners/lots.csv`)
only drug, notice date, entry date, exit date, ticker, net return and hedge are sent. A summary is
rejected and retried if it is not two sentences or contains a number that is not in those facts;
nothing is written unless every trade passes. `results/explanations.json` records the model, the
UTC timestamp, the prompt, the source file and its SHA-256. `GET /api/explain/{lot_id}` returns the
cached text (404 if absent) with `current: false` when the source file has changed since generation.

## FDA Time Machine (Tiger Data)

`/time-machine.html` shows each drug's latest archived FDA shortage page on or before a chosen
date (UTC), with its status, manufacturers, archive time and Wayback link, so you can see what
was public on any day without hindsight. Click a drug for its status timeline.

```bash
uv run --extra dashboard python scripts/load_tiger.py --dry-run   # build rows only
uv run --extra dashboard python scripts/load_tiger.py             # hypertable + bulk load
```

The loader creates `backfill_live.fda_snapshots(snapshot_ts, drug, manufacturer, status, source_url)`
as a hypertable on `snapshot_ts` and loads one row per archived capture, drug and manufacturer from
`results/forward_oct2024/suppliers.csv` (18,218 rows, 1,042 drugs, 2014-07-14 to 2026-09-23). Each
drug keeps one canonical name (its latest display name). Endpoints, read-only and cached 60 s:
`/api/fda/asof?date=YYYY-MM-DD` and `/api/fda/timeline?drug=...`. If Tiger is unreachable they
return `state: "error"` with a message; a bad date returns a JSON error. The timeline merges
same-day captures, because FDA can list one drug on several tabs at once.



Tiger Data is the time-series database, not a source of stock prices or FDA
notices. Your Webull/FDA collector must send sourced observations into it.
The dashboard reads those observations and shows their source timestamps,
ingestion timestamps and freshness. Market quotes older than five minutes are
labeled stale; daily or closed-market quotes may therefore be correctly stale.
Automatic polling runs every 15 seconds and pauses in a hidden browser tab.
The live-history chart reads the last seven days of actual stored quotes for
FMS, ICUI or SPY, capped at the most recent 2,000 observations. It selects one
recorded vendor per chart and keeps freshness/source labels visible. It never
modifies the frozen historical chart or substitutes historical data as live.

1. Provision the service and use its connection details. Set
   `TIGER_DATABASE_URL` in the root `.env` or process environment; do not paste
   credentials into the UI. Use a SELECT-only role for the dashboard.
2. An operator runs `dashboard/schema.sql` once to create `backfill_live.quotes`
   and `backfill_live.supplier_updates`. Optional TimescaleDB hypertable commands
   are commented in that file; nothing runs a migration automatically.
3. Ingest observations from your existing sources, using a separate writer
   connection in `TIGER_INGEST_DATABASE_URL`:

```bash
uv run python -m dashboard.ingest --kind quotes --file /path/to/vendor_quotes.csv --dry-run
uv run python -m dashboard.ingest --kind quotes --file /path/to/vendor_quotes.csv
uv run python -m dashboard.ingest --kind supplier_updates --file /path/to/fda_updates.csv
```

Quote CSV columns: `time,ticker,price,previous_close,volume,source`.
Supply CSV columns:
`observed_at,event_key,product,company,ticker,availability,source,source_url,status`
(`status` is optional; run `python -m dashboard.apply_schema` once to add the column).
Timestamps must include a timezone and cannot be in the future. Prices must be
positive/finite. Availability is `available`, `allocation`, `disrupted` or
`unknown`. Supplier updates require a public source URL. Duplicate observations
are ignored without rewriting prior records. `received_at` is database-generated
ingestion time; never substitute it for the source's observation time.

**Archived FDA notices.** `python -m dashboard.collect_fda_notices --out notices.csv` writes the
newest archived snapshot of each drug captured in the 30 days before the latest capture, one row per
supplier, with page status and the exact Wayback URL (matched on timestamp *and* drug, since one
archive second can hold several pages). The card groups rows into one notice per drug snapshot and
shows the 10 newest, each labeled "Archived FDA page, snapshot YYYY-MM-DD": point-in-time records,
not live signals.

**Stale quotes.** Quotes older than five minutes keep the "Stale" badge (with a tooltip). On a
weekend or NYSE holiday, if the newest stored quote is the last session close, a note explains it:
"Markets closed - showing last close (Fri Oct 2, 4:00 PM ET)", built from the stored timestamp.
On trading days no note is shown and the normal stale warning stands (`market_hours.py`).

Read sessions have a connection timeout, statement timeout and read-only
transaction. Connection errors sent to the browser omit driver details that
could contain credentials. Default TLS mode is `require`; preserve verified
certificate settings in your deployment. Set `TIGER_SSLMODE=verify-full` with
the appropriate trust store when available. `disable` is for explicit local
database testing only.

Reference: [Tiger Data Python/PostgreSQL integration](https://www.tigerdata.com/learn/building-python-apps-with-postgresql-and-psycopg3),
[Psycopg transaction management](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

## Small structure

| File | Responsibility |
|---|---|
| `repository.py` | Saved research artifacts → display records and allowed downloads |
| `tiger.py` | Read-only, bounded live queries and connection states |
| `server.py` | Local HTTP/API server and static assets |
| `ingest.py` | Explicit, validated observation ingestion |
| `collect_fda_notices.py` | Archived FDA detail-page captures → supplier_updates CSV |
| `apply_schema.py` | Operator command to apply `schema.sql` (idempotent) |
| `fda_history.py` | FDA Time Machine as-of and timeline queries (read-only, cached) |
| `market_hours.py` | NYSE calendar used only to explain stale quotes |
| `audit.py` | Research audit from Snowflake with a 10-minute cache and file fallback |
| `proof.py` | Saved Solana receipt and cached live re-verification of `freeze-v1` |
| `schema.sql` | Operator-run table creation |
| `static/tokens.css` | Rezt tokens, fonts, themes and primitives |
| `static/app.css` | Responsive page and instrument geometry |
| `static/app.js` | API-driven UI, filtering, source drawer and live polling |
| `static/dial.js` | Actual source-hash coverage; draws only when needed |
| `static/case.js` | Saved case charts, source policies, hedge decomposition and capital illustration |
| `export_case.py` | Verify existing files and package derived case observations without a backtest |
| `data/helene_case.json` | Derived session curves, saved cashflows and case provenance |
| `data/reported_basket.json` | Reported teammate metrics with provenance, not a new rerun |

Change colors/fonts in `tokens.css`; add sections in `index.html`; keep derived
research ingestion in `repository.py`. Browser requests cannot write to the
database, change rules, execute SQL, run tests or consume a holdout lock.
Font licenses are alongside the self-hosted WOFF2 files.
