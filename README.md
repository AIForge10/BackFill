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

```bash
uv sync && uv run python examples/backtest/main.py
```

> [!WARNING]
> Everything dated on or after **2024-10-01** is the out-of-sample
> holdout. The backtest runner refuses those dates unless
> `WEBULL_ALLOW_OOS=true`, and the pipeline scripts skip them unless you
> pass `--final`. That run happens once, at the end, and only Aaryan
> runs it.

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
company_ticker_map.csv  →  events → positions (05, next)  →  backtest runner
```

---

## Documentation

- **[`HYPOTHESIS.md`](HYPOTHESIS.md)** — the pre-registered claim,
  definitions, test rules and in-sample/out-of-sample split.
- **[`docs/USAGE_EN.md`](docs/USAGE_EN.md)** — the Webull backtest kit:
  credentials, every `.env` setting, report output.

## Directory layout

```
Gator_Hacks/
├── HYPOTHESIS.md            pre-registration (commit before any backtest)
├── config.py                shared settings: holdout, gap days, costs, caps
├── pyproject.toml           one uv environment for pipeline + backtest
├── src/
│   ├── 01_wayback_index.py  CDX index + coverage table (gaps across years)
│   ├── 02_fetch.py          polite resumable download (--years, --shard, --only-needed)
│   ├── 03_parse_main.py     list pages → main_status.csv, shortage_events.csv
│   └── 04_parse_details.py  detail pages → suppliers.csv (rule-tagged availability)
├── data/
│   ├── company_ticker_map.csv   supplier regex → listed parent, listing windows
│   ├── processed/           built by src/ (indexes, events, suppliers, logs), gitignored
│   └── raw/                 Wayback HTML cache, gitignored (~140 MB)
├── examples/
│   ├── backtest/main.py     backtest runner (Webull data, holdout lock, run log)
│   └── strategies/          one file per strategy; branches work only here
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

### 3. Run a backtest (in-sample)

```bash
uv run python examples/backtest/main.py
```

Every run writes `results/<label>/metrics.json` and `equity.csv`, and
appends one row to `results/variants_log.csv`. Don't delete rows: the
note discloses every variant tried.

## Building the data

No data is committed. The FDA pages are rebuilt from the Wayback Machine,
and prices come from Webull when the backtest runs. Run these once, in
order, before the first backtest. The full build takes about 4 hours
because Wayback is fetched at about 1 request per second.

| Command | What it does |
|---|---|
| `uv run python src/01_wayback_index.py` | Lists every capture; writes `index_*.csv` and `coverage_main.csv` |
| `uv run python src/02_fetch.py --which main --years 2014-2024` | One main-page snapshot per ISO week |
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
- **Reproduction needs the Wayback Machine online.** The archive was
  "Temporarily Offline" once during development. If that happens, wait
  and re-run: every fetch is resumable.
- **The ticker map is incomplete.** 117 companies with 801 "Available"
  rows are unmapped, for example West-Ward (now Hikma), Akorn, AuroMedics
  and AbbVie. Extending `data/company_ticker_map.csv` is the cheapest way
  to grow the sample.
- **Webull data is US-only.** Winners listed abroad (FRE.DE, HIK.L,
  SDZ.SW, .NS names) need yfinance prices, or the test is restricted to
  US-listed names and the restriction disclosed.
- **Events → positions (`src/05_events.py`) isn't built yet.** The
  strategy reads `data/events.csv` (`event_date, drug, ticker, side`),
  which doesn't exist yet.
- **The strategy kit doesn't match the pre-registration yet.**
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
