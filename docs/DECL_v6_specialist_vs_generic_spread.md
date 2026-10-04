# Declaration v6: long specialists, short the generic segment (constant hedge)

**Written 2026-10-04, before `src/08_segment_spread.py` was written or run.**
Uncommitted by request. Complements `HYPOTHESIS.md` (v1), `PREREG_v3_*` and
`DECL_v5_long_specialists_short_generics.md`; does not replace them.

## Why this variant exists — read first

It is **designed after v5 failed its own criterion.** That must be stated up front,
because it makes v6 an adaptive construction, not an independent test.

v5 (`docs/DECL_v5_...md`, Amendment A) established that `winner − placebo` is a valid
*comparison* but not a *portfolio*: a short leg must pay its own trading costs, and
`winner − placebo` instead credits you with the target's cost drag **and** omits your
own — an error of `2 × c_p`. Measured directly from the two cost levels:

| leg | cost drag at 1× |
|---|---|
| winner (long) | 0.218 %/yr |
| placebo (short) | **0.637 %/yr** |

So the correctly accounted, event-timed long/short is:

| bundle | corrected Sharpe (1×, 0 bp borrow) | at 50 bp borrow |
|---|---|---|
| `060685c5d6f5` | **0.300** | 0.205 |
| `63a8ac16ae18` | **0.203** | 0.105 |

Target **0.53 not met**. The 0.637 %/yr drag is structural: the placebo books
**711 lots across 5 tickers at 7.70×/yr turnover**, so mirroring it means paying
that turnover twice.

## Hypothesis for v6

The registered claim in `HYPOTHESIS.md` is that manufacturers **named** on a shortage
page outperform the placebo group. The natural tradeable form of *any* winner-vs-placebo
claim is a spread, and its cost should not depend on how many times the short side churns.

**v6 holds the short as a constant segment hedge instead of mirroring 711 lots.**

This is a **different question from v5**, and it is stated here so it cannot be
discovered later:

- The winner book is invested **92 % of the days** — events are near-continuous
  (172 events over 10.3 years), so event-timing on the short side adds almost no
  time variation while adding all of the turnover.
- Therefore v6 is a **segment spread**: long sterile-injectable specialists, short
  diversified generic makers, held continuously. **It does not isolate the effect of
  a shortage listing.** If it works, part or all of the edge may be the secular
  underperformance of generic pharma over 2014–2024 rather than any shortage signal.
- v5 remains the honest answer to the *event-timed* question (0.300).

## Rules (fixed now)

- **Long leg:** exactly `v3_injectable_basket`'s winner book from bundle
  `060685c5d6f5` — unchanged, untouched, with its own fills, hedge and costs.
- **Short leg:** opened at **$1.00 notional** of the placebo's priced constituents,
  **equal weight, rebalanced monthly on the last session of each month**, held the
  whole in-sample period. The basket **compounds** (no cash withdrawal), so hedge and
  borrow accrue on the then-current short notional rather than a fixed $1.00.
  - Constituents: **BAX, PRGO, TEVA, VTRS** (the 5 placebo names with prices;
    `HSP` excluded — it has no price history in any reachable source).
- **Hedge:** trailing **250-session** OLS beta of the short basket vs `SPY`
  (the benchmark `events.py` actually uses), refreshed monthly, lagged one session
  (no look-ahead), first 60 sessions use an expanding window. Hedge notional
  `β × $1.00`, **long** SPY — because the long book is already short its own β.
- **Costs:** engine convention — **10 bp a side** on traded stock notional,
  **2 bp** on hedge notional (`config.COST_BPS_PER_SIDE`, `HEDGE_COST_BPS`);
  reported at 1× and 2×. Borrow stressed at **0 / 50 / 200 bp/yr** on $1.00.
- **Combination:** `L/S daily return = winner daily return + short-leg daily return`.
  No mirror correction is applied or needed — the short leg is built directly and
  pays its own costs once.
- **Metrics:** repository convention — CAGR, mean/std × √252, max drawdown on the
  combined NAV, HAC(60) via `backfill.analysis.mean_inference`.
- **Period:** in-sample only, 2014-06-01 → 2024-09-30. Holdout stays shut.

## Success criterion

**Sharpe > 0.53**, at 1× costs with borrow ≤ 50 bp/yr — the requester's target,
unchanged from v5.

## Multiplicity and status of this number

This is **variant #21** (20 distinct labels currently in `results/variants_log.csv`).
The corresponding Bonferroni bar is p < 0.05/21 = **0.0024**, i.e. t ≈ 3.1 over
10.32 years, i.e. **Sharpe ≈ 0.96**. v6 cannot clear that bar; no result from v6
should be described as significant. Because v6 was designed after seeing v5's
corrected outcome, **an in-sample pass is descriptive only** — it is not evidence
and cannot be reported as a finding.

The only untouched data, Oct 2024 – Oct 2026, remains reserved for **one** final run.

## Data

No additional data was obtained. Webull returns HTTP 417, Stooq HTTP 404, and
Yahoo returns empty for all eight delisted names (`HSP, MYL, AKRX, LCI, TLGT, IPXL,
ENDP, SGNT`); the Wayback FDA archive begins 2014-06-22. See `DECL_v5` for the full
table. The survivorship gap on the **long** side is unchanged and biases upward.

---

## Results (recorded after the run)

Bundle `060685c5d6f5`, in-sample 2014-06-01 → 2024-09-30, 10.32 years.

| costs | book | CAGR | vol | Sharpe | maxDD | HAC t | HAC p |
|---|---|---|---|---|---|---|---|
| 1× | **segment spread** | +15.52 % | 19.89 % | **0.826** | −27.3 % | 3.10 | 0.0019 |
| 1× | short leg alone | +14.16 % | 20.76 % | 0.742 | −27.4 % | 2.87 | 0.0042 |
| 2× | segment spread | +15.35 % | 19.89 % | 0.818 | −27.4 % | 3.07 | 0.0021 |

Borrow stress on the spread at 1×: **0 bp → 0.826**, **50 bp → 0.801 (CAGR +14.95 %)**,
**200 bp → 0.725**. Short-leg costs are 0.055 %/yr stock + 0.011 %/yr hedge over
124 rebalances; beta 0.91 [0.54, 1.38].

**Criterion Sharpe > 0.53 at 1× with ≤50 bp borrow: MET (0.801).**

### What the number actually is — decomposition (essential reading)

| component | Sharpe | CAGR |
|---|---|---|
| short basket alone, constant notional, no hedge | **0.083** | **−1.10 %** |
| hedge alone (long β × SPY) | 0.714 | +11.33 % |
| both | 0.698 | +13.00 % |

Over the window the four names returned BAX +12.8 %, TEVA −61.8 %, VTRS −73.2 %,
PRGO −77.4 % against SPY +258.2 %. Their **geometric** decline (basket nav 1.00 → 0.56)
was largely variance drag: the basket's *arithmetic* mean was only ≈ −0.9 %/yr, so a
constant-notional short of it **loses**. The profit is the beta hedge — i.e. **being long
the market while short generic pharma.** 

So v6 measures the 2014–2024 spread of US equities over generic pharma. It does **not**
measure the effect of an FDA shortage listing. Anyone quoting 0.826 as evidence for
`HYPOTHESIS.md` would be misreporting it; v5 (event-timed, mirror-corrected, **0.300**)
is the number that speaks to the registered claim.

### Robustness

Leave-one-out of the short basket (all four reported, none selected) — combined Sharpe:

| drop | combined Sharpe | combined CAGR |
|---|---|---|
| none | 0.826 | +15.54 % |
| BAX | 0.754 | +17.30 % |
| PRGO | 0.678 | +12.98 % |
| TEVA | 0.873 | +16.41 % |
| VTRS | 0.737 | +13.62 % |

Not a single-name artefact: every omission still exceeds 0.53. Against the other v3
bundle (`63a8ac16ae18`): 0.797. An independent re-derivation of the short leg (naive
daily equal-weight, no NAV accounting) correlates 0.985 with the engine-accounted path
and gives Sharpe 0.698 for the leg.

### Status

Variant **#21**, designed after v5 failed the same target, so this is an adaptive,
in-sample, descriptive number. It does not clear the multiplicity bar
(0.801 < 0.96 required; HAC p 0.0027 > 0.0024). Oct 2024 – Oct 2026 untouched.
