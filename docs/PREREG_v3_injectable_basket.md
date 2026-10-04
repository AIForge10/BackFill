# Pre-registration v3: injectable shortages and the specialist basket

Written 2026-10-03, **before** this variant was implemented or run. It is a new
hypothesis, not a replacement for `HYPOTHESIS.md` (v1), which stays as registered.

## What we already saw (disclosure)

- v1 (buy the named available supplier) and 12 related variants lost money
  in-sample; none was significant. All are in `results/variants_log.csv`.
- A specialist basket restricted to events with an archived supplier page
  (12 events) earned +2.22% a year (Sharpe 0.67, p = 0.040). On those 10
  unique dates the 4 traded names earned +16.2% hedged over 60 sessions,
  against about +1.5% on random dates.
- This v3 was chosen after seeing those results. It must be judged mainly on
  the out-of-sample period (October 2024 to October 2026).

## Hypothesis

Listed US sterile-injectable specialists outperform the market over the 60
trading sessions after the FDA first lists a sterile-injectable shortage,
because hospitals cannot easily substitute injectables and the few remaining
makers gain volume and pricing power, while investors wait for earnings.

## Rules (fixed now)

- **Events:** every shortage in `data/processed/shortage_events.csv` whose
  product name matches `inject|infusion|intravenous`, excluding left-censored,
  rename-window, spike-week and rename-suspect events, and events more than 60
  days after the previous archived list page. **No supplier page is required.**
- **Trade date:** next US session close after the public date (known at UTC day end).
- **Long book:** every US-listed company flagged `specialist = 1` in
  `data/company_ticker_map_v2.csv`, listed on the trade date, ADRs excluded.
- **Capital:** 10% of NAV per event, split equally across those names.
  A name without price history (delisted) keeps its share in **cash**; it is
  never moved to the other names.
- **Hedge / hold / costs / caps:** as the Backfill primary (SPY beta from 250
  prior returns, 60 sessions, 10 bp per side, 8% per name, drawdown halving),
  also reported at 2x costs.
- **Placebo:** US-listed non-specialist generic makers listed on the trade
  date, same dates and capital.

## Success criteria (all required in-sample, then out-of-sample)

1. Annualized return and Sharpe positive, HAC p < 0.05.
2. Still positive at 2x costs.
3. Beats the placebo (winner-minus-placebo p < 0.05).
4. Basket return on event dates above the 95th percentile of random-date draws.
5. No single name drives the result (leave-one-name-out stays positive).

One in-sample run. Whatever it shows is reported.
