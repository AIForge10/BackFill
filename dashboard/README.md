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

- Hypothesis first: the refined supplier mechanism, exact 20-session delay /
  five-session hold, strict availability rule and beta-sized short-SPY hedge.
  The page explicitly labels the refinement as formed after in-sample research.
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

## Connect Tiger Data

Tiger Data is the time-series database, not a source of stock prices or FDA
notices. Your Webull/FDA collector must send sourced observations into it.
The dashboard reads those observations and shows their source timestamps,
ingestion timestamps and freshness. Market quotes older than five minutes are
labeled stale; daily or closed-market quotes may therefore be correctly stale.
Automatic polling runs every 15 seconds and pauses in a hidden browser tab.

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
`observed_at,event_key,product,company,ticker,availability,source,source_url`.
Timestamps must include a timezone and cannot be in the future. Prices must be
positive/finite. Availability is `available`, `allocation`, `disrupted` or
`unknown`. Supplier updates require a public source URL. Duplicate observations
are ignored without rewriting prior records. `received_at` is database-generated
ingestion time; never substitute it for the source's observation time.

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
