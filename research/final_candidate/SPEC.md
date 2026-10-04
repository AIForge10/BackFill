# Final candidate v1 - frozen 2026-10-04

This is the team's current **exploratory working candidate**, selected after
in-sample results were inspected. It does not replace HYPOTHESIS.md or the
registered 60-session primary. Every prior result remains part of the record.

## Frozen rule

- June 2014 through September 2024; US listed suppliers only.
- On one archived formulation page selected with the original 30-day window,
  every presentation for the contemporaneous listed parent must be available,
  unallocated and nonempty. These are FDA-listed presentations, not a complete
  company catalogue or proof of spare manufacturing capacity.
- Information date is the later shortage observation/supplier capture date.
  First eligible fill is the next US session close. **Enter 20 additional US
  sessions after that close; exit five session intervals after actual entry.**
- No SMA filter in v1. Re-estimate beta from exactly 250 paired stock/SPY
  returns ending before entry; freeze the hedge through the lot's life.
- 5% capital per event divided among strict US winners, including unpriced
  shares that remain cash. Aggregate 8% name, 30% market, 50% healthcare-sector,
  150% gross and 25% absolute-net caps. Independent lots retain their expiries.
- Cash earns zero. Stock 10bp and SPY 2bp per side, actual exit notional;
  assumed hedge carry 50bp/year. Stress doubles both fees and carry.
- Reduce exposure after a 10% drawdown, restore after 20 sessions. No early
  shortage-resolution exit. Delayed entries do not assume supplier status was
  reverified at entry; this evidence-staleness limitation is disclosed.
- Reference results retain their recorded vendor mix: Webull plus disclosed
  Yahoo TEVA fallback. New reports show **Webull-only** separately. No new
  quotes are fetched or predecessor history aliased. SPY is the US calendar.

## Authorized comparison, fixed before evaluating it

On exactly the same frozen strict supplier sample, compare v1 against one
alternative: initial preceding close below SMA60, immediate next-session close
entry, same five-session hold. Preserve event weights before price filtering;
rejected allocations remain cash. Also report the alternative with a separately
listed parent disrupted on the same formulation page. Exact strength/route
substitutability is an evidence audit; unverified matches are never claimed as
confirmed commercial substitutes. There is no additional timing/threshold grid.

Report each at normal/doubled costs, with same-date FDA-page-absent controls,
and each vendor policy separately. Keep all stocks, including AMRX. Already
completed company/year omission and nearby-timing results are retained. A
control absent from the FDA page is not a verified nonmanufacturer.

Replacement requires higher normal AND doubled-cost Sharpe than v1 under the
SAME vendor policy, positive winner-minus-control mean, no worse drawdown,
at least ten unique stock/date exposures across at least three stock owners,
and positive mean retained-lot return after each company omission. Nominal
significance does not erase prior searches. If the screen is unmet, keep v1.
No replacing a strategy by cherry-picking a different sample, vendor or period.

The existing 2024-2026 period has been inspected. Do not run --final, reset a
holdout lock, create a new blind-OOS label or change freeze-oos. Confirmation of
a new rule needs genuinely unseen events. This candidate is final for current
working purposes, not statistically validated or fully competition-certified.

## Required analysis and reproducibility

Save exact requests, eligibility, trades, lot cashflows, daily NAV, the six
required portfolio metrics, cost stress, equity curve, pre-information drift,
company/year concentration, same-date controls, market/value/momentum factor
exposures, and lagged ADV/spread capacity estimates. Preserve source, price,
code and factor hashes and append a dedicated lifecycle log. Missing factor
data is reported explicitly rather than substituted or fabricated.

Frozen ledgers are in data/processed/final_candidate/v1. Raw quote caches stay
gitignored. Reproduce offline with:

    python -m research.final_candidate.run

The command uses only the local frozen cache; a cache miss stops it. Source
changes require a new version and a disclosed data-quality variant.
