# Corrected exploratory timeframe screen

Date: 2026-10-03. Written after inspecting the original primary and the existing
gross 25-cell scan, before calculating the net portfolios in this new screen.
This is post-result exploratory research, never a revised registered primary.

The source is the frozen US in-sample primary ledger from bundle `222584aadc36`
and its exact cached prices. Preserve the original owner map, data exclusions,
timing, beta, risk limits, cash and accounting. No network acquisition or holdout
data is permitted. All price hashes and original fingerprinted files must match.

## Bounded family

- Winner groups: all winners; dated generic-maker winners; injectable-product
  winners (product name contains `injection` or `injectable`). The last group is
  a formulation heuristic, not proof of parent revenue exposure/specialization.
- Holds: 1, 5, 20, 40, 60, 120, 250 local sessions. No additional intervals selected
  after observing this screen. This produces 21 strategy cells.
- Each cell runs at original costs and doubled costs. Each uses the real daily
  portfolio engine and includes transaction costs, hedge carry, caps and expiry.
- Equal capital per event within each group. Price-excluded winners retain their
  intended cash allocation. Dropping a company based on outcomes is prohibited.
- Controls are the existing nonlisted generic-maker controls on the same events
  as the cell's price-eligible winners. Controls retain their known limitation:
  absence from the FDA page is not verified nonmanufacture. Every matched event
  must have controls. Each group has its own matched control calendar-time portfolio.
- Report HAC mean-return tests for winners and winner-minus-control (max of 60
  and hold sessions), using the complete common calendar including idle days.
- Correct the 84 new mean tests jointly with Holm, conservatively counting the
  25 already-inspected gross cells, secondary test and earnings test as additional
  prior trials (27 placeholder p-values set to one). This does not make the
  discovery sample independent or guarantee valid small-sample inference.
- Record all started/completed/failed portfolios in this isolated branch's
  `results/variants_log.csv`; save all requests, equity, lots, trades, exclusions,
  source hashes and comparisons. Original result files/logs are preserved.

## Advancement gate

Positive net winner and paired means, adjusted p < 0.05 for both, at least ten
unique ticker/entry-date exposures and at least three winner tickers must hold at
both cost levels. Any nominee also requires positive neighboring-horizon means
and leave-one-company/year-out net portfolio checks before promotion. Those
diagnostics are conditional on a nominee and must also be logged, with no
parameter changes. A survivor is an exploratory candidate, not confirmed alpha.

Reproduce the original primary winner metrics in the all-winners/60/normal-cost
cell. A discrepancy stops the screen. Any missing/mutated data stops the screen.
Report every cell regardless of sign; retain null and negative outcomes.
