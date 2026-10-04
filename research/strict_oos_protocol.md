# Strict supplier timing: single holdout batch

Written 2026-10-03 before loading holdout prices or evaluating holdout returns.
The in-sample timing search is exploratory. These are two selected rules from a
bounded grid, not the best rules among all possible timeframes.

## Fixed comparisons

US listings, the existing dated owner map, supplier capture window 30 calendar
days, and the existing event exclusions. Every parent-owned presentation row on
the selected archived FDA formulation page must be available, not allocated,
and have a nonempty presentation. This does not establish a complete catalogue
or spare manufacturing capacity.

1. Wait 20 additional local sessions after the first evidence-eligible close;
   enter at that close and hold for exactly 5 local sessions.
2. Enter at the first evidence-eligible close and hold for 250 local sessions.

Report each with and without AMRX, without redistributing omitted capital.
AMRX omission is a pre-specified sensitivity to the observed in-sample outlier,
not a second opportunity to select the better result. The registered ordinary
available-supplier 60-session primary remains a separate reported comparison.
No new timeframes, supplier definitions, ticker omissions or map extensions may
be selected after viewing this holdout.

## Evidence and accounting

Holdout: 2024-10-01 through 2026-10-01 inclusive. Use a separate source vintage
and price cache. Preserve exact archived capture timestamps, point-in-time
owner mapping, next-session-close execution and 250 preceding paired returns
for beta. The entry delay must not cause beta to use entry-day information.
Use the existing event weights, company/portfolio caps, drawdown rules, cost
assumptions and hedge carry. Report normal and doubled costs with contemporary
FDA-page nonlisted controls, which are not verified nonmanufacturers.

Do not replace missing archives with today's FDA page. Audit migration layout
coverage and the year-long list gap explicitly: first observation after a gap
does not prove the first public shortage announcement. Never convert an
unparseable page to evidence of product absence. Missing evidence, failed
parsing, missing prices and holds ending after the fixed cutoff receive distinct
exclusion reasons; never shorten holds to force a reported outcome.

## One-time evaluation and reporting

Before evaluation, freeze and commit all runnable specifications, accounting
code and source identities, require a clean `freeze-oos` revision, and reserve
the existing shared `results/backfill_oos_attempt.json` before loading returns.
Evaluate the frozen comparisons together; keep started/completed/failed logs
and never clear the attempt lock. Data readiness checks are not evaluations and
must not load prices or report investment performance.

Report sample sizes, executed and excluded lots, unique stock-date exposures,
average/median net lot returns, hit rate, annualized portfolio return,
volatility, Sharpe, drawdown, turnover, equity curve, HAC uncertainty and
winner-minus-control inference. Disclose all in-sample searches and report all
holdout comparisons, including negative results. Zero eligible lots means
metrics unavailable, not a zero-return successful strategy. A tiny sample does
not constitute reliable confirmation even if its realized returns are positive.
