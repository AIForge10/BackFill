# Backfill: the first working research version

The primary strategy is deliberately small: available suppliers only, equal
capital per event, a frozen pre-entry beta hedge, and 60 local session intervals.
**Primary scope is US listings** (team decision 2026-10-03: Webull, the sponsor
data source, covers US listings). Non-US winners are the declared `all_markets`
variant, to be enabled later.
`HYPOTHESIS.md` is unchanged. The Webull/backtrader examples remain separate.

## Where to edit

| File | Responsibility |
|---|---|
| `strategies/primary.py` | Which candidates become lot requests; equal-event weights |
| `backfill/settings.py` | Explicit hold, beta, costs, exposure limits and risk settings |
| `config.py` | Shared dates, broad-market references/proxies and original caps |
| `data/company_ticker_map.csv` | Effective-dated supplier-to-owner mapping |
| `backfill/events.py` | Capture selection, allocation exclusion, evidence and controls |
| `backfill/prices.py` | Explicit acquisition and strict offline cache loading |
| `backfill/engine.py` | Scheduling, independent lots, fills, cash, hedges, FX and expiry |
| `backfill/analysis.py` | Metrics, HAC inference, descriptive pre-drift, ADV and spread reports |
| `backfill/guardrails.py` | Run identity, append-only logging and one-attempt holdout lock |
| `backfill/pipeline.py` | CLI orchestration and the fixed variant registry |
| `backfill/selection.py` | The fixed selection rule applied to completed in-sample outputs |
| `tests/test_backfill.py` | Hand-computed synthetic accounting and bias regressions |

No work runs on import. Strategies never fetch prices or calculate portfolio
performance. The engine never imports a vendor. There is no optimizer, plugin
framework, or automatic search.

## Start without evaluating anything

From the repo root, using the existing environment:

```bash
uv run python run_all.py --prepare-only
uv run python -m unittest discover -s tests -v
```

Preparation reads the existing FDA tables and writes
`data/processed/backfill/primary/{events.csv,attrition.csv,attrition_summary.csv,preparation.json}`.
It recomputes rename flags using only names known by each event date. Source
hashes detect a parser changing input files during preparation. No returns are
loaded. The unit tests use invented prices and temporary files, including their
own temporary run log; they never touch the real research trial log.

`uv run python src/05_events.py` is the equivalent standalone preparation step.

## Explicit acquisition, then offline evaluation

```bash
uv run python src/06_prices.py
uv run python run_all.py
```

The second command evaluates and logs the primary winner and control portfolios,
each at normal and doubled costs. Only run it when ready to examine results.
It writes four reports in `results/backfill/<bundle-id>/primary/`, plus paired
winner-minus-control returns and HAC inference. Each report contains equity,
trades, lots, eligibility, metrics, a plot, capacity and descriptive pre-drift.

Only `06_prices.py` invokes a vendor. **Vendor policy (default `--vendor webull`):**
US stocks and ETFs come from the Webull OpenAPI, using the credentials in
`examples/backtest/.env`. yfinance serves only what Webull cannot: index calendars
(`^GSPC`), FX, non-US listings, and any symbol where Webull failed. Each fallback
is recorded with its reason. Webull daily bars are forward-adjusted ("previous
weight" in the SDK). Whether that includes dividends is undocumented, so every
Webull series is cross-checked against Yahoo's adjusted close:
- **Date overlap and return correlation** must both be at least 0.95. Otherwise the
  symbol falls back to Yahoo, and the failed check is recorded as the reason. On
  2026-10-03 this applied to TEVA (Webull had 650 of about 2,950 sessions) and RDY
  (return correlation 0.21).
- **`annualized_log_return_gap`** shows the dividend treatment. A gap near the
  dividend yield means Webull omits dividends.

`--vendor yfinance` reproduces everything without Webull keys. Cache misses, altered
hashes, invalid bars, failed cross-checks and unresolved acquisition failures stop
evaluation. Prices live in the already
gitignored `data/raw/prices/is/`. A manifest records requests, actual coverage,
vendor version, retrieval times, adjustments and SHA-256 hashes. A changed
request/exclusion set needs a new cache directory rather than silently overwriting
the old data version.

HSP and MYL are requested under their actual historical symbols. **There is no
automatic VTRS alias.** If historical prices cannot be verified, an operator can
explicitly exclude the stock with a reason, in a new cache version:

```bash
uv run python src/06_prices.py --cache data/raw/prices/is-v2 \
  --exclude 'HSP=Historical delisted prices unavailable from the verified source'
uv run python run_all.py --cache data/raw/prices/is-v2
```

Exclusions are disclosed in the manifest and lot eligibility. The winner's
intended share of event capital stays unallocated; retained winners are not
silently upweighted. A missing bar *during an initiated hold* is different: it
stops the run and requires a corporate-action/data audit. It never drops a loser.

The default universe also includes nonlisted generic-maker controls, so its
symbol count can exceed the winner-only estimate. LSE equity/ETF OHLC and
dividends are converted from Yahoo's GBp convention to GBP; volume is preserved.
Vendor history/adjustment suitability must still be verified before relying on
real results. The implementation has been verified on synthetic inputs only.

## Exact rules and accounting assumptions

- First observed list date is conservatively known at UTC day end. Select one
  event page: latest capture within the prior 30 days, otherwise first capture
  within the next 30 days. Selection never searches for favorable availability.
  A multi-key event uses a single page, with lexical `ai_key` tie-breaking; other
  formulation pages are not silently combined using future supplier knowledge.
- Primary winners are `available` **and not on allocation**. Preserve every
  matched presentation quotation. A mixed supplier can qualify through one
  available presentation while its other presentation states remain disclosed.
  The formulation-level `ai_key`, never the coarse recurrence key, joins suppliers.
- Entry is the next local session's close after the trade-ready date; exit is
  close `entry_index + 60`. Entry-day returns before the fill earn nothing.
- Beta uses exactly 250 paired local-currency returns, all ending before entry.
  Insufficient entry-known history is disclosed. New securities cannot borrow
  predecessor price history. The beta is frozen for that lot.
- Each event requests 5% NAV, split across its distinct listed winners. Overlaps
  create separate lots and expiries. Allocate same-day requests simultaneously;
  clip to 8% company, 30% listing-country, 50% healthcare long, 150% gross,
  25% absolute dollar-net and 20% non-USD long limits. Clipped capital remains cash.
- Caps also reduce lagged drifted exposures at the next local close. They are
  decision-time limits; overnight moves/closed markets can exceed them until the
  next executable adjustment. Stock and hedge are always adjusted together.
- A 10% drawdown from the NAV high triggers halving at next local closes. Restore
  after 20 portfolio sessions, preserving lot expiries. A continued drawdown can
  retrigger at a subsequent close. All adjustments incur costs.
- No shortage-resolution exit, disrupted short, volatility targeting or
  earnings-based filter is part of primary.
- Both legs use adjusted-close **total-return valuation units**, not purported
  raw execution shares. Daily FX marks produce USD NAV; GBP/EUR/CHF quotes are
  USD per local unit and INR quotes are inverted. FX is unhedged. Daily closing
  FX marks idealize asynchronous execution and are not intraday fill evidence.
- Cash earns zero. The Sharpe uses zero as the cash benchmark and says so.
  Registered per-side costs remain intact. Hedge carry is a disclosed assumed
  50 bps/year on absolute hedge notional, accrued by elapsed calendar days.
  Doubled-cost reports also double carry. This is not a market-verified borrow
  quote. Change it only as a disclosed sensitivity, not an unlogged improvement.
- Local session dates come from separately cached market-index series; holidays
  carry the last stock mark, while a missing stock bar on a reference session
  fails. Audit reference-index completeness before real evaluation.
- Each lot is transacted separately, conservatively charging costs without
  cross-lot order netting. ADV reports sum absolute same-symbol transactions.
  Capacity reports are participation bounds at 1% and 5%, not estimated
  profitable capacity. Position sizes are not retrospectively reduced using
  future exit liquidity. Corwin–Schultz is a spread diagnostic, not a calibrated
  impact model; a zero estimate does not establish free execution.

Broad index references are S&P 500, FTSE 100, DAX, SMI and Nifty 50. Adjusted-close
ETF proxies are SPY, ISF.L, EXS1.DE, CSSMI.SW and NIFTYBEES.NS. Their actual history,
currency and tracking suitability need checking at acquisition. The old config
mixed sector/broad benchmarks; the primary now follows the hypothesis wording.

## Controls and inference: what this version can establish

Controls are contemporaneously listed generic makers in the same listing markets
whose parents have **no row on the chosen FDA page**, including nonwinner rows.
Their event capital is equally split across controls. This is an unmatched
FDA-page nonlisted control portfolio. It is **not proof of nonmanufacture** and
does not fully implement the registered strict placebo. The ledger, comparison
and selection files explicitly carry that limitation.

Primary inference is calendar-time mean return with 60-lag HAC standard errors
(120 lags for the 120-session variant);
there is no independent-event CAR t-statistic. Pre-entry CARs are descriptive and
may include days after the public listing. An optional supplied monthly USD
decimal factor CSV can be passed using `--factors`; it needs
`date,Mkt-RF,HML,Mom,RF`. No daily forward-filling of monthly factors is performed.
Factor-region suitability and small-sample uncertainty remain research judgments.

Next methodological additions should be dated product/catalogue evidence and
matched controls, block-bootstrap intervals, equivalence tests, regional factor
checks and calibrated impact. They are deliberately not hidden inside the first
engine. Full competition evidence requires these limitations to be addressed or
clearly disclosed; passing unit tests is not evidence of a trading edge.

## Small variant set and final freeze

`--variant` accepts primary plus eight predeclared alternatives: `capture60`,
`allocation`, `certain_dates`, `all_flags`, `hold20`, `hold40`, `hold120`, `all_markets`.
Each changes one dimension. `--leave-out PFE` is an in-sample omission diagnostic
that preserves the original winner allocations. No disrupted-short variant is
added automatically. The teammate's existing strategy is unchanged and remains
a separately disclosed existing specification.

Prepare variant ledgers before acquisition when needed. `06_prices.py --events`
accepts multiple ledger paths to acquire their union into one data vintage. Every
evaluation logs started/completed/failed records in `results/variants_log.csv`;
count distinct run IDs, not lifecycle rows. Bundle identities fingerprint source
data, code, settings and cache manifest. Existing sponsor log rows are preserved.

After completing the declared in-sample comparisons:

```bash
uv run python -m backfill.selection
```

This reads existing outputs only. **The holdout always evaluates the registered
primary.** Picking the variant with the best in-sample Sharpe would be a best-of-N
selection, which the track brief warns against. Other completed variants are only
recorded (Sharpe, control p-value, placebo gate), so the note can disclose every
variant tried. The command rejects mixed code/data vintages and ignores omission
diagnostics. It requires a completed primary bundle at both cost levels.
Nonsignificance is not equivalence, and p-values are raw (no multiple-testing
adjustment).

Commit the reviewed selection/code/data, then tag that clean commit `freeze-oos`.
Do not run a holdout during development. The later `--final --variant primary`
command requires that tag at HEAD and a clean tree, checks the frozen code and
mapping, and reserves an attempt **before** loading price returns. Failed/partial
attempts stay locked. There is intentionally no retry override.

OOS signal tables must be provided separately, using `--events-source`,
`--suppliers-source` and `--status-source` (prefer gitignored `data/raw/oos/`).
`05_events.py --oos-stage` and `06_prices.py --oos-stage` are frozen data stages,
not evaluations. OOS acquisition uses a separate cache through October 1, 2026
inclusive, with prior history for beta. The one final bundle reports the registered
primary with its controls and doubled costs. The primary remains the 60-session test.

The default final lock is `results/backfill_oos_attempt.json`. Git/local files
provide an operational guard, not tamper-proof enforcement. Keep that record and
all logs; do not delete them to repeat an evaluation. The live Webull sponsor demo
has its own original controls; it is not the primary research entry point.

## Reproduction

The public FDA-derived ledgers and tests are redistributable. A gitignored vendor
cache does not by itself make a public clone reproduce a note exactly. Preserve
manifests, dependency versions and authorized acquisition instructions; redistribute
the exact normalized price inputs only where the applicable license permits it.
