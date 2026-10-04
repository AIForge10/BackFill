# Backfill

**From FDA shortage notices to auditable supplier-trading research.**

Backfill reconstructs historical shortage notices and supplier availability from
Internet Archive captures, maps each supplier to its listed owner at that date,
and tests whether manufacturers that can still supply a drug outperform their
market hedge.

**Start here:** [Five-page research note](output/pdf/backfill_working_candidate_v1.pdf)
· [Results and limitations](results/research/final_candidate_v1_20261004/RESULTS.md)

## What we found

The original US strategy entered at the next eligible close and held for 60
sessions. Its 19 trades did **not support the hypothesis**: net Sharpe **−0.59**.

Our current **exploratory candidate** uses a stricter supplier definition:

1. Every FDA-listed presentation for the company on the selected archived
   formulation page must be available, unallocated and nonempty.
2. Wait until both the shortage observation and supplier evidence are available.
   Identify the next US session close, then enter **20 additional sessions later**.
3. Exit **five trading sessions after entry**, hedged against SPY using a beta
   fitted from 250 prior paired returns.

The timing was selected after inspecting in-sample results. It is a research
candidate, not confirmation of the original hypothesis.

### In-sample results · June 2014–September 2024

| Metric | Historical reference | Webull-only check |
|---|---:|---:|
| Trades / events | 8 / 7 | 4 / 3 |
| Average net return on lot capital | +2.84% | +5.40% |
| Portfolio Sharpe | 0.53 | 0.61 |
| Sharpe with doubled costs | 0.49 | 0.59 |
| Maximum drawdown | −0.22% | −0.22% |

The reference uses Webull plus **four recorded Yahoo-priced TEVA trades**.
The Webull-only check leaves their allocations in cash. Each event requests 5%
of capital, split among its winners; portfolio metrics include inactive cash.
The reference annualized portfolio return is +0.105%, not +2.84%.

**The limitation matters:** AMRX contributes 87% of net dollar profit. Without
it, reference Sharpe falls to **0.10**. Winner HAC p-value is **0.279**; the result
is not statistically significant. The inspected 2024–2026 period cannot serve
as a new blind holdout for this refined candidate. Indicative spreads also
exceed the frozen cost assumption, so execution-cost calibration remains open.

## How we back it up

- **Dated evidence:** archived supplier pages, presentation-level availability,
  effective-dated owner mapping and recorded exclusions for missing delisted prices.
- **Auditable accounting:** next-close fills, separate overlapping lots,
  pre-entry beta hedges, modeled costs and carry, exposure caps and cashflow reconciliation.
- **Visible research history:** controls, doubled costs, nearby timing,
  company/year omissions, uncertainty, factor exposure and ADV/spread capacity.
  Two fixed entry alternatives failed the replacement gate; neither replaced the candidate.

[Full metrics, comparisons and audit files](results/research/final_candidate_v1_20261004/20261004T045406Z_8db48a/)
· [Price provenance](data/processed/final_candidate/v1/price_manifest.json)

## Run or review

For the interactive research and Tiger Data monitor:

```bash
uv sync --extra dashboard
uv run python -m dashboard.server
```

Open [localhost:8080](http://127.0.0.1:8080). Inspect saved results, FDA evidence,
cashflows and source hashes. [Dashboard setup](dashboard/README.md) explains
the live database connection and ingestion; historical views work without it.

From the repository root:

```bash
uv sync
uv run python -m unittest discover -s tests
```

All **27 tests pass** using synthetic accounting and guardrail fixtures; no
vendor keys or real-price cache are required for the tests.

With the frozen licensed cache at `data/raw/prices/final_candidate_v1/`:

```bash
uv run python -m research.final_candidate.run
```

This reproduces the working candidate and fixed comparisons offline. Missing or
altered inputs stop the run. Derived evidence, results and manifests are
committed; licensed raw prices are gitignored. Exact numerical reproduction
requires that frozen cache. A fresh vendor download is a different data vintage.

## Explore the implementation

[Exact strategy specification](research/final_candidate/SPEC.md)
· [Small module structure and editing guide](research/final_candidate/README.md)
· [Original pipeline documentation](docs/BACKFILL.md)

The available-supplier signal lives in `research/final_candidate/`; the shared
accounting engine lives in `backfill/`. Preserve v1 and its results when adding
a new disclosed experiment. Webull sponsor examples remain in `examples/`.
