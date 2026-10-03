# Sharper hypothesis: shortage gains show up at the next earnings announcement

*Pushed before any return in this test was computed. The commit timestamp is the record.*

## Status (disclosed)
Written after three in-sample results were not supported: the registered primary (60-day hold),
the secondary (disrupted suppliers) and a 25-cell exploratory grid (no cell survived Holm).
This test sharpens the **mechanism already stated in HYPOTHESIS.md**: "investors wait for earnings
instead of reading FDA supply notices." The 60-day test measured the wrong window if the price only
moves when the extra sales are reported.

## Hypothesis
After the FDA first lists a shortage, a listed supplier marked **Available** shows an unusually
**positive** stock reaction at its **first earnings announcement after entry**, relative to its own
typical earnings reaction.

## Data
- **Events and winners:** the primary's events, supplier-page rule and dated owner map; US listings;
  HSP and MYL excluded (no prices). Entry date from the engine's scheduler.
- **Earnings dates:** SEC EDGAR 8-K filings with Item 2.02 ("Results of Operations"), filing date
  = announcement date. Companies filing earnings on 6-K (foreign private issuers, e.g. Teva before
  2018, Dr. Reddy's) have no Item 2.02 dates and are excluded and disclosed.
- **Prices:** the validated cache `data/raw/prices/is`.

## Measurement
- **Announcement reaction:** return over trading days -1 to +1 around the filing date, minus
  beta x SPY return over the same days (beta from 250 sessions before the shortage entry).
- **Post-shortage reaction:** the first Item 2.02 filing between entry and entry + 120 calendar days.
- **Baseline:** the same company's mean reaction over all its other Item 2.02 filings, 2014-2024,
  excluding every post-shortage announcement.
- **Abnormal earnings reaction (AER):** post-shortage reaction minus baseline.

## Test and decision rule (fixed now)
- **One test:** mean AER across winner positions > 0, one-sample t-test, two-sided p < 0.05,
  with at least 10 positions. Reported with a Wilcoxon signed-rank p as a check.
- **Reported alongside (descriptive, not tested):** the same AER for disrupted suppliers and controls,
  per-position table, by company.
- One in-sample evaluation. If supported, confirmed once on the holdout before any claim.
