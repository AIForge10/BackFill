<div align="center">
  <h1>Backfill</h1>
</div>

<div align="center">
  <h3>Trade the drugmakers that can still ship when the FDA posts a
  shortage, using supplier history the FDA itself deletes.</h3>
</div>

<div align="center">
  <img src="https://img.shields.io/badge/python-3.12-3776AB" alt="Python 3.12">
  <img src="https://img.shields.io/badge/env-uv-DE5FE9" alt="Environment: uv">
  <img src="https://img.shields.io/badge/data-Wayback%20Machine-555555" alt="Data: Wayback Machine">
  <img src="https://img.shields.io/badge/holdout-locked%20from%202024--10--01-critical" alt="Holdout locked from 2024-10-01">
</div>

<br>

When a drug goes into shortage, hospitals have to buy from the suppliers
that still have product. Backfill rebuilds the FDA drug-shortage history
from Wayback Machine snapshots (2014–2024). It dates each shortage from
the first archived page that shows it, reads which companies were listed
"Available" on the archived detail page, and backtests those companies
against their market index. The hypothesis, pre-registered before any
backtest, is in [`HYPOTHESIS.md`](HYPOTHESIS.md).

## For judges: reproduce the results

```bash
uv sync                                   # or: python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # optional: Webull keys; without them, prices come from yfinance
uv run python run_all.py                  # signals -> prices -> backtest -> summary (in-sample)
```

`run_all.py` rebuilds the signals from the committed FDA tables, fetches daily prices once
(the only network step; prices are licensed, so they are never committed), runs the registered
backtest offline and prints the summary table (also saved as `results/backfill/<run>/summary.md`).
No Webull keys? Run `uv run python data/download.py prices --vendor yfinance` first.

| Step | Script | What it does |
|---|---|---|
| Data | `data/download.py` | `prices` (daily bars), `release` (the team's archived FDA pages), `fda-csv` (FDA CSV exports for the 2024–25 gap), `rebuild` (re-fetch everything from Wayback) |
| Signals | `src/signals.py` | Shortage events + point-in-time supplier evidence (wraps steps 03, 03b, 04, 05) |
| Backtest | `src/backtest.py` | Offline lot engine: next-close entry, 60-session hold, beta hedge, costs; `--variant` for declared variants |
| Analysis | `src/analysis.py` | Headline table: return, volatility, Sharpe, drawdown, turnover, worst month, HAC t, winners vs controls |
| Tests | `uv run python -m unittest discover -s tests` | Synthetic accounting, point-in-time and holdout-lock tests |

> [!WARNING]
> Everything dated on or after **2024-10-01** is the out-of-sample
> holdout. The new offline research runner requires a clean `freeze-oos`
> tag, frozen selection and one-attempt lock for `--final`. That run happens
> once, at the end, and only Aaryan runs it. The Webull example retains its
> separate original environment-based guard.

The primary research entry point is now a small **pandas lot engine**. Read
[`docs/BACKFILL.md`](docs/BACKFILL.md) for the module boundaries, precise rules,
remaining methodological limitations and offline workflow. Acquire prices
explicitly with `src/06_prices.py`; `run_all.py` never accesses a vendor.
The Webull/backtrader examples are preserved as the sponsor demonstration.

## Why use Backfill?

- **Rebuilds deleted data** — the FDA removes resolved shortages from
  its site. The archive restores 395 weekly list pages and 898 supplier
  pages from 2014 to 2024.
- **Point-in-time suppliers** — a company counts as a winner only if an
  archived page dated on or before the trade date lists it as
  "Available". Today's supplier lists are never used.
- **Survives FDA renames** — events are detected on an ingredient-level
  `coarse_key`. Without it, the FDA's September 2023 renaming would have
  created about 180 fake "new" shortages in a single week.
- **Flags instead of silent filters** — events are tagged
  `date_uncertain`, `rename_window`, `spike_week`, `rename_suspect` or
  `left_censored`. The primary test excludes the flagged ones, and
  robustness runs add them back.

```
Wayback CDX  →  fetch (1 req/s)  →  parse main list  →  shortage_events.csv
 (01_index)       (02_fetch)         (03_parse_main)     (476 events, 335 primary)
                                  →  parse detail pages →  suppliers.csv
                                     (04_parse_details)    (6,384 company rows)
                                                              ↓
company_ticker_map.csv  →  evidence + attrition (05)  →  cached-price lot engine
```

---

## Documentation

- **[`HYPOTHESIS.md`](HYPOTHESIS.md)** — the pre-registered claim,
  definitions, test rules and in-sample/out-of-sample split.
- **[`docs/BACKFILL.md`](docs/BACKFILL.md)** — the new primary strategy,
  cached-price pandas engine, synthetic tests, audits and extension points.
- **[`docs/USAGE_EN.md`](docs/USAGE_EN.md)** — the Webull backtest kit:
  credentials, every `.env` setting, report output.

## Directory layout

```
Gator_Hacks/
├── README.md                setup + one command to run
├── run_all.py               reproduces the note (signals → prices → backtest → summary)
├── requirements.txt         dependencies (also pyproject.toml / uv.lock)
├── .env.example             Webull keys template; .env stays out of git
├── HYPOTHESIS.md            pre-registration (commit before any backtest)
├── config.py                shared settings: holdout, gap days, costs, caps
├── data/
│   ├── download.py          download scripts: prices, team release, FDA CSVs, full rebuild
│   ├── company_ticker_map.csv   supplier regex → listed parent, listing windows
│   ├── processed/           derived FDA tables, committed (indexes, events, suppliers)
│   └── raw/                 caches (archived pages, CSV copies, prices), gitignored
├── src/
│   ├── signals.py           build signals (runs 03, 03b, 04, 05)
│   ├── backtest.py          run the offline backtest
│   ├── analysis.py          headline metrics table
│   ├── 01_wayback_index.py  CDX index + coverage table (gaps across years)
│   ├── 02_fetch.py          polite resumable download (--years, --shard, --only-needed)
│   ├── 03_parse_main.py     list pages → main_status.csv, shortage_events.csv
│   ├── 03b_parse_fda_csv.py archived FDA CSV exports → fda_csv_rows.csv (2024–25 gap)
│   ├── 04_parse_details.py  detail pages → suppliers.csv (rule-tagged availability)
│   ├── 05_events.py         point-in-time evidence ledger + attrition
│   └── 06_prices.py         explicit price acquisition (Webull for US, yfinance fallback) + immutable manifest
├── strategies/primary.py   pure primary signal selection
├── backfill/               settings, evidence, cache, lot engine, analysis, guards
├── tests/                  synthetic accounting and point-in-time regression cases
├── examples/
│   ├── backtest/main.py     backtest runner (Webull data, holdout lock, run log)
│   └── strategies/          preserved sponsor/demo specifications
├── webull_bt/               Webull data feed + broker library for backtrader
├── results/                 variants_log.csv (every run) + one folder per run
├── research/                quick tests run before pre-registration (disclosed)
└── docs/                    Webull kit guides
```

### Why the pipeline keys events on `coarse_key` but matches on `ai_key`

`ai_key` is the normalized `AI=` (active ingredient) value from the FDA's
detail-page links.
Detail pages are archived under exactly this name, so it's the only safe
join key between events and suppliers. But the FDA renames products:
"Amoxapine Tablets" became "amoxapine tablet" on 2023-09-16. So the
180-day "new shortage" test runs on a coarser key that strips dosage
forms, strengths, brands and packaging. Each event keeps every `ai_key`
that was Current on its first day, so detail matching still works.

### Where the keys live

`examples/backtest/.env` holds the Webull keys and every backtest
setting, and the runner reads it. It's covered by `**/.env` in
`.gitignore`. **Never put real keys in a `.env.example`**: those files
are tracked. This happened once in this repo and was caught before the
first commit.

## Setup

### 1. Install

```bash
uv sync                      # Python 3.12, all pipeline + backtest dependencies
# or, without uv:  python -m venv .venv && .venv/bin/pip install -r requirements.txt
uv run python -c "import webull_bt, bs4, backtrader; print('ok')"   # should print ok
```

### 2. Add Webull credentials

```bash
cp examples/backtest/.env.example examples/backtest/.env
# fill WEBULL_APP_KEY / WEBULL_APP_SECRET; confirm WEBULL_API_ENDPOINT with the team
```

**Never commit this file.** It's covered by `**/.env` in `.gitignore`.

### 3. Run the sponsor demo (in-sample)

```bash
uv run python examples/backtest/main.py
```

Every run writes `results/<label>/metrics.json` and `equity.csv`, and
appends one row to `results/variants_log.csv`. Don't delete rows: the
note discloses every variant tried.

## Building the data

The derived FDA tables in `data/processed/` are committed. They come from
public-domain US government pages, so you don't need to rebuild them.
The raw HTML and price caches are not committed. The primary engine reads
an explicitly acquired immutable cache; only the separate sponsor demo uses
live Webull fetching. To rebuild the FDA data from scratch, run these
in order. Raw pages go to `data/raw/{main,detail}/YYYY/`, one folder per
capture year, so a team can fetch different years in parallel and merge
by copying folders. `--workers 8` keeps several requests in flight while
staying at 1 request per second.

| Command | What it does |
|---|---|
| `uv run python src/01_wayback_index.py` | Lists every capture; writes `index_*.csv` and `coverage_main.csv` |
| `uv run python src/02_fetch.py --which main --years 2014-2024 --workers 8` | One main-page snapshot per ISO week |
| `uv run python src/03_parse_main.py` | Status panel and shortage events with flags |
| `uv run python src/02_fetch.py --only-needed` | For each event, the detail capture on or before `public_date + 7d`, plus a backup |
| `uv run python src/04_parse_details.py` | Company × presentation rows with `availability` |

All fetches are resumable: re-running skips files already on disk, and
`fetch_log_*.csv` keeps the latest status for each capture.

## Known gaps

- **The main page has a 364-day hole (2024-09-06 → 2025-09-05).** During
  that year the FDA list redirected to `dps.fda.gov`, a Next.js app whose
  archived pages contain no rows. openFDA was first archived in May 2025.
  The hole falls almost entirely in the out-of-sample window and is
  recorded in `data/processed/coverage_main.csv`.
- **Detail pages were archived late, not missing.** 455 of 476 events
  match a detail page by name. But only about 141 primary events have a
  supplier page within 30 days of the shortage date, and only about 32
  have an "Available" supplier the seed ticker map can trade. 2017–2018
  contribute almost nothing because the archive barely crawled detail
  pages then.
- **A rebuild from scratch needs the Wayback Machine online.** The
  committed tables avoid this for normal use. The archive was
  "Temporarily Offline" once during development; if it happens, wait and
  re-run, because every fetch is resumable.
- **The ticker map is incomplete.** 117 companies with 801 "Available"
  rows are unmapped, for example West-Ward (now Hikma), Akorn, AuroMedics
  and AbbVie. Extending `data/company_ticker_map.csv` is the cheapest way
  to grow the sample.
- **The primary test covers US listings only.** Webull, the sponsor data
  source, serves US listings, so the primary has 25 events and 27 winner
  positions. Non-US winners (FRE.DE, HIK.L, .NS names) are the declared
  `all_markets` variant, priced from yfinance.
- **Delisted owners may have no prices.** MYL (Mylan, before Viatris) and HSP
  (Hospira, before Pfizer) are 7 of the 27 US winner positions, and Yahoo has
  no history for either. Unless Webull serves them, they're excluded and
  disclosed (`06_prices.py --exclude`), never silently remapped.
- **The initial controls are FDA-page nonlisted generic makers.** They
  are not verified nonmanufacturers. Strict product-absence evidence and
  matching remain extensions; the current comparison discloses this limitation.
- **The separate sponsor strategy doesn't match the primary.**
  `examples/strategies/shortage_events.py` defaults to a 40-day hold,
  shorts disrupted companies, hedges everything with XLV and uses 15 bp
  costs. `HYPOTHESIS.md` specifies 60 days, long winners only, a
  local-index beta hedge, and the per-country costs in `config.py`.
- **222 supplier rows are `unknown`** ("TBD", "N/A", empty) and
  count as non-winners. Treating them otherwise is a disclosed variant.

## Troubleshooting

```bash
uv run python src/03_parse_main.py | tail -12    # event counts + flags
grep -v ",ok," data/processed/fetch_log_main.csv # downloads still failing
git check-ignore -v examples/backtest/.env        # must print a .gitignore rule
```

**`SDK.HttpError ('Connection aborted.', ConnectionResetError(54, ...))`
on startup.** The Webull SDK resets during client setup, before any
data request, so your keys aren't the problem yet. Check that your
network can reach `WEBULL_API_ENDPOINT` (the template's sandbox host
versus `api.webull.com`). VPNs and network sandboxes can block it.

**`OOS lock: WEBULL_TODATE must be set and earlier than 2024-10-01...`**
The runner is protecting the holdout. Keep `WEBULL_TODATE` at or before
`2024-09-30`. `WEBULL_ALLOW_OOS=true` is reserved for the single final
run.

**A week shows hundreds of "new" shortages.** That's an FDA rename or a
garbled page, not a market event. Check the `rename_window`,
`spike_week` and `rename_suspect` columns in `shortage_events.csv`
before trusting it.

## Architecture history

1. **Per-name events → ingredient-level `coarse_key`.** The FDA's
   September 2023 rename produced 180 fake events in one week.
2. **Absolute spike threshold → rate per elapsed week.** The first rule
   flagged 36% of events, mostly real backlogs after archive gaps.
   Backlogs are now `date_uncertain`, and spikes are rate-based.
3. **Cutting product names at the first `;` → cutting only before packaging text.**
   Old names use `;` between combination ingredients ("isoniazid;
   rifampin"); only the 2024 package listings use it before packaging.
