# Strict-availability entry/exit exploration

Written 2026-10-03 after all earlier exploratory results, before this timing grid.
The evaluated primary stays unchanged. This is an in-sample exploratory variant.

Signal: every listed-parent presentation on the selected archived FDA page is
available, with no allocation or missing presentation; use the original 30-day
capture rule. US listings only because that is the verified cached universe.
Keep three MYL exclusions, event capital, frozen-entry beta, caps, cash, carry and
costs as implemented. Available at the signal date does not guarantee availability
20 sessions later; this grid deliberately uses the original evidence, not future
status updates. No catalogue-completeness or spare-capacity claim is made.

Buy at the first local close after evidence is known, or wait exactly 5 or 20
additional local sessions. Re-estimate beta from the 250 returns ending before
the actual delayed entry. Sell at close entry_index + H, for H in
1, 5, 20, 40, 60, 120, 250 sessions. All holds must finish before October 2024.
No intrahold winning/losing-trade filter or outcome-dependent exit is permitted.

Compare original supplier evidence and the frozen refreshed supplier snapshot as
separate data vintages. Both contain eleven strict US candidates; one TEVA event's
newly recovered earlier page advances the information cutoff. These are highly
dependent comparisons, not new independent validation observations.

42 strategy cells = two vintages x three delays x seven holds. At each, evaluate
winners and same-event nonlisted FDA-page controls at normal and doubled costs
(168 portfolio evaluations). Controls carry their existing nonmanufacture caveat.
All runs are logged with sources/code hashes in this isolated research branch.

Report annualized return/volatility, Sharpe, drawdown, turnover, equity, HAC mean
and paired winner-minus-control tests (lags=max(60,H)). Also report per-lot net
P&L/entry capital, average, median, win count, ticker, entry and exit dates.
Allocate lagged hedge carry to each lot and reconcile the sum of lot net P&L
with the engine's total final NAV change. Do not confuse a lot return with an
annualized portfolio return.

Correct the 168 new mean tests jointly with Holm, retaining at least 111 prior
inspected probes as p=1 placeholders (the earlier 84 net mean tests plus 27 counted
gross/secondary/earnings tests). This is a conservative screen, not exhaustive
accounting of every historical research decision or independent confirmation.

A timing candidate needs positive net and paired means and adjusted p<0.05 at
both cost levels, ten unique ticker/entry-date exposures and at least three
winner tickers. Then examine nearby intervals and company/year omission checks.
Show the highest-Sharpe cell even if it fails; label it selected from this grid.
Do not change the grid or pick stocks after observing its results. No prices are
fetched, no holdout is loaded, and original result bundles/logs are preserved.
