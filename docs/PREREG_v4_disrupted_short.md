# Pre-registration v4: companies disrupted by the shortage

Written 2026-10-03, **before** this variant was implemented or run. A separate
hypothesis from `HYPOTHESIS.md` (v1) and v3; neither is changed.

## What we already saw (disclosure)

v1, 12 related variants, the 12-event specialist basket and the pre-registered
v3 (173 events) were all run in-sample; none passed (see
`results/variants_log.csv`). The guide's old `shortage_events.py` also shorted
the company in shortage; no one on this branch has seen its results on real events.

## Hypothesis

A US-listed company that the FDA detail page marks as **disrupted** for a drug
newly in shortage underperforms the market over the next 60 trading sessions,
because it loses sales, faces FDA scrutiny and pays for remediation, while
investors wait for earnings to see it.

## Rules (fixed now)

- **Events and pages:** exactly the primary's: one FDA detail page per event
  (latest capture within 30 days before listing, else first within 30 days
  after), same flag exclusions, in-sample June 2014 to September 2024.
- **Book:** every US-listed parent (`data/company_ticker_map_v2.csv`) with at
  least one presentation marked `disrupted` on that page and none `available`.
- **Accounting:** the engine is long-only, so the book is measured long,
  hedged with SPY (beta from 250 prior returns), 60 sessions, 5% of NAV per
  event split across names, 10 bp per side. **A negative hedged return is the
  short's profit**; a real short also pays borrow, not modelled beyond the
  engine's 50 bp/year hedge carry.
- **Placebo:** US-listed generic makers not named on that page, same dates.
- Names without price history keep their share in cash.

## Success criteria (in-sample, then out-of-sample)

1. Book's annualized return negative and Sharpe below zero with HAC p < 0.05.
2. Still negative at 2x costs.
3. Book below placebo with winner-minus-placebo p < 0.05.

One in-sample run. Whatever it shows is reported.
