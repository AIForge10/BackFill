# Secondary hypothesis: disrupted suppliers underperform

*Written and pushed before this test was run. The commit timestamp is the record.*

## Status and origin (disclosed)
- **Secondary, not a replacement.** The registered primary in `HYPOTHESIS.md` is unchanged and is reported as registered.
- **Written after** the primary's in-sample result was seen (US primary, 2014–2024: winners' Sharpe −0.59, p = 0.16). **Before** any return of disrupted suppliers was computed.
- **The idea predates the results.** `PLAN.md` step 7 defined the disrupted role ("Disrupted = availability == disrupted AND listed"). The sponsor-kit strategy committed to `main` this morning (`examples/strategies/shortage_events.py`, commit 2293f21) shorts disrupted companies.

## Hypothesis
When the FDA first lists a shortage, **listed companies that the archived FDA page shows as unable to supply** (backordered, unavailable, limited, delayed) **underperform their local market over the next 60 trading days.** A maker that can't ship usually has a manufacturing, quality or capacity problem behind it, which costs revenue and remediation. The shortage notice is an early public sign of that.

## Definitions (identical to the primary unless stated)
- **Events:** the primary's events, flags and supplier-page rule (one page per event: latest capture in the prior 30 days, else first in the next 30), mapped to the owner listed on the trade-ready date.
- **Disrupted:** a listed company whose rows on that page are `disrupted` and none `available`. Events qualify if they have at least one disrupted listed company, **whether or not** they have a winner.
- **Scope:** US listings; HSP and MYL excluded (no vendor history), as in the primary.
- **Trade:** short each disrupted company at the next local close after the information is known; hold 60 sessions; hedge by going long the local index proxy (SPY) at the pre-entry 250-session beta; 5% of capital per event split across its disrupted names.
- **Costs:** the primary's per-side costs on both legs, plus an assumed 50 bps/year stock-borrow fee.

## Test and decision rule (fixed now)
- **Measured on the hedged long portfolio of disrupted names;** the short's return is its negative minus borrow costs.
- **Supported** if the disrupted names' mean hedged return is **negative** with two-sided HAC p < 0.05 (60 lags), at normal and doubled costs.
- **Reported regardless** of outcome, together with the per-trade table, by-year results and pre-entry drift. One in-sample evaluation; the holdout is tested once at the end with the primary.
