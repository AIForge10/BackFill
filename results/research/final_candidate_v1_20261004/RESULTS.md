# Backfill working candidate v1 - final for current research

**Decision: retain strict availability, entry delay 20 sessions, hold 5 sessions.** This is a post-result exploratory candidate. The original hypothesis and registered 60-session primary remain visible; this does not validate them.

The previously evaluated US primary had 19 lots / 17 events, Sharpe -0.594, annualized return -0.56%, volatility 0.94%, drawdown -6.66%, annual turnover 23.79%, and HAC p=0.156. It did not support the hypothesis. Its source metrics and provenance are preserved separately as a reporting reference.

## Exact rule

Every FDA-listed presentation for the contemporaneous listed parent on the selected archived formulation page must be available, unallocated and nonempty. Information becomes usable after both shortage observation and supplier capture. Identify the next US session close, wait 20 additional US sessions, enter at that close, and exit five session intervals later. No SMA filter. Status is not reverified during the waiting period.

Beta is fitted from 250 prior stock/SPY returns, ending before entry, and stays fixed. Allocate 5% per event, split before filtering or exclusions; rejected allocations stay cash. US stocks only. 8% name, 30% market, 50% sector, 150% gross, 25% absolute-net caps. De-risk after a 10% drawdown at the next session, restoring after 20 sessions. Cash return is zero.

## Actual in-sample results

June 2014-September 2024. Costs: stock 10bp/SPY 2bp per side plus 50bp/year hedge carry. Doubled-cost runs double both fees and carry. The historical reference uses Yahoo TEVA fallbacks; Webull-only excludes those allocations without upweighting other names.

| Policy / rule | Lots / events | Sharpe | Sharpe x2 costs | Mean net lot | CAGR | Volatility | Max DD | Annual turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| reference_mix / delay20_hold5 | 8 / 7 | 0.535 | 0.495 | +2.84% | +0.105% | +0.198% | -0.22% | 12.87% |
| reference_mix / below_sma60_hold5 | 3 / 3 | 0.087 | 0.061 | +0.86% | +0.012% | +0.142% | -0.43% | 5.55% |
| reference_mix / below_sma60_disrupted_hold5 | 1 / 1 | 0.411 | 0.399 | +9.61% | +0.046% | +0.113% | -0.07% | 1.97% |
| webull_only / delay20_hold5 | 4 / 3 | 0.609 | 0.591 | +5.40% | +0.100% | +0.165% | -0.22% | 5.23% |
| webull_only / below_sma60_hold5 | 2 / 2 | 0.390 | 0.367 | +4.81% | +0.046% | +0.120% | -0.07% | 3.75% |
| webull_only / below_sma60_disrupted_hold5 | 1 / 1 | 0.411 | 0.399 | +9.61% | +0.046% | +0.113% | -0.07% | 1.97% |

## Replacement decision

Neither alternative passes the prewritten replacement gate: improve Sharpe at both costs on the same vendor policy; positive winner-minus-control mean; no worse drawdown; at least ten unique exposures across three owners; positive retained-lot mean after every company omission. The disruption-filtered discount rule is only one AMRX observation. The current candidate itself also lacks ten exposures and is not certified as a robust edge.

## Inference and concentration

Winner HAC p=0.279; winner-minus-page-absent controls p=0.207. Seven information-date clusters; descriptive bootstrap mean-lot 95% interval -0.86% to +8.23%. These intervals are conditional on the selected sample and are not selection-adjusted.

AMRX contributes 87.0% of net dollar P&L. Excluding it leaves mean net lot +0.52% and Sharpe 0.104. Its omitted allocation remains cash. Mean pre-information descriptive CAR is -3.04%; this cannot be described as flat or as evidence that prediction P3 passed.

Search disclosure: the preserved strict timing study has 42 strategy cells, 168 winner/control portfolio evaluations and 38 omission diagnostics; it records 111 earlier inference probes. A separate entry grid tested nine rules on another sample. This package compares two further entry/filter rules against the retained baseline, under two vendor policies and two cost assumptions (24 winner/control evaluations). Identical reruns corrected a serialization failure and verified the final audit; all attempts remain recorded. The known lower-bound multiplicity adjustment gives p=1 for all current winner tests. Counts are dependent and the older 111-probe inventory is not an exhaustive count of distinct strategies.

## Factor, risk and capacity checks

Monthly US market/value/momentum regression uses 124 months, official Ken French factors and HAC(3). Coefficients: market -0.00122, value 0.00236, momentum -0.00208. Monthly cash-benchmark alpha -0.115% (t=-4.46). This negative alpha reflects, in part, zero-return idle cash versus the factor risk-free rate. Factor vintage is retrospective, never an entry signal.

Measured max marked gross 10.76%, max name 5.78%, max absolute net 2.77%; 35/2601 active days; no drawdown de-risk trigger. Sparse exposure and idle cash limit tail/regime claims.

Dollar ADV uses 60 prior sessions and capacity=min(0.01*ADV/order_fraction) across both legs and entry/exit orders. Estimated limiting AUM is $461,086 at 1% ADV, $2,305,430 at 5%. $1m is an accounting normalization, not a claim of executable capacity; AMRX exit is about 2.19% ADV at that size. These are volume-based bounds, not profitable capacity estimates.

Corwin-Schultz median full-spread estimates for AMRX are about 89bp, above the assumed 20bp round-trip stock fee. Even doubled stock costs are below this indicative spread. The fixed-cost results are a model benchmark pending execution-cost calibration. Webull adjustment/dividend and historical volume conventions are not independently certified; capacity is provisional. A zero spread estimate does not establish free execution.

## Data and validation

Frozen strict ledger: 18 all-market candidates across 15 events; 11 US candidates, with three MYL candidates excluded for unavailable predecessor prices. Eight scheduled reference lots remain. Every strict winner matches the frozen all-presentation audit. The Webull-only reference has four lots across three events; four TEVA reference lots use disclosed Yahoo prices. No prices were fetched by this evaluation; SPY supplies the US calendar and hedge.

Every evaluation saves requests, filter/eligibility reasons, trades, lot cashflows, daily NAV, metrics, equity curve, capacity, factor coefficients and pre-information drift. Lot cashflows reconcile with NAV; the eight-lot reference reproduces the preserved figures exactly. 27 synthetic/guardrail tests pass. All price and input hashes are verified; primary files, hypothesis, config, original variants log and holdout lock are unchanged.

## Holdout and next evidence

There is no new blind out-of-sample result for this refined candidate. The 2024-2026 period has already been inspected. No formal final command was run, no lock reset, and no tuning of a claimed invisible test period. A genuinely unseen future event cohort and a calibrated spread/impact model are needed before upgrading this exploratory relation to a validated edge. Historical holdout comparisons, if later shown, must be labeled exposed-sample research.

## Reproduce and edit

Run `.venv/bin/python -m research.final_candidate.run` offline with the frozen licensed cache. Missing, short or altered files stop the run. Read `research/final_candidate/README.md` to create a new disclosed version; do not overwrite v1 or automatically replace the primary.

Detailed run: `results/research/final_candidate_v1_20261004/20261004T045406Z_8db48a`. Sources: frozen FDA ledger/audit, cache manifest, and [official Ken French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html).
