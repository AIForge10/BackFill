# All-presentations-available supplier variant

2026-10-03. Defined and prepared after the original primary and timeframe results
were seen. This is a disclosed exploratory change to the supplier definition,
not a retroactive replacement of the evaluated primary.

## Exact rule

A listed owner qualifies for an event only when every row belonging to that owner
on the single selected archived FDA product/formulation page:

1. Has a nonempty presentation description.
2. Is classified `available` by the existing availability parser.
3. Is not marked on allocation.

One disrupted, unknown, discontinued, allocated or unidentified presentation
rejects that owner/event. Apply the existing dated owner mapping at the trade-ready
date; combine all subsidiary/company rows belonging to the same listed parent.
Contradictory rows are not silently removed. Empty groups never qualify.

Keep the same event flags and capture-selection policy. Information remains known
only when the chosen page is public; no backdating to the first shortage listing.
The statement means every presentation **listed on that FDA page**, not a verified
complete manufacturer catalogue or verified spare production capacity.

## Prepared counts from existing in-sample FDA tables

| Scope and supplier-page window | Current-rule candidates | Strict-rule candidates | Strict events |
|---|---:|---:|---:|
| US, original 30-day window | 26 | 11 | 10 |
| All existing mapped markets, original 30-day window | 42 | 18 | 15 |
| All existing mapped markets, disclosed 60-day window | 62 | 26 | 23 |

For the original 30-day window, US strict candidates are TEVA (4), MYL (3), PFE
(1), BAX (1), ICUI (1), AMRX (1). With the existing cache and recorded MYL exclusion,
eight US positions across seven events schedule successfully for 60 sessions.
These are eligibility counts, not executed backtest or return results.

Seven additional non-US candidates in the original window are Fresenius
`FRE.DE` (2), Novartis `NOVN.SW` (1), Aurobindo `AUROPHARMA.NS` (1), Alembic
`APLLTD.NS` (1), Torrent `TORNTPHARM.NS` (1) and Zydus `ZYDUSLIFE.NS` (1),
under the unchanged existing map. Their prices were not fetched or evaluated.

The 60-day capture variant adds eight owner/event candidates: BAX for vancomycin,
cefepime and CRRT solutions; MYL for levetiracetam; NOVN.SW for amphetamine salts;
TEVA for vecuronium; FRE.DE for IV fat emulsion; CAPLIPOINT.NS for etomidate.
This combines a stricter supplier rule with a longer evidence window and must be
disclosed as two changed dimensions. Later evidence implies later entry.

The strict definition alone cannot increase the sample: it is a subset of the
previous any-available-presentation winners. More observations require independent
owner-map research, wider market coverage or additional archived evidence. The
pending owner-map extension remains separate; no ticker mapping was changed here.

## Implementation and verification

`research/full_availability.py` prepares all-market original-window and extended-
window audit/evidence/strict-winner ledgers without vendors or portfolio returns.
It checks that source presentation counts match the candidate ledger evidence,
and verifies source hashes before/after preparation. All 27 unit tests passed,
including mixed-status, unknown, allocation, missing-presentation and empty-group
cases. Original configuration, hypothesis, result bundles and holdout are untouched.

Files are in `data/processed/full_availability/capture30/` and `capture60/`;
`preparation.json` records counts, source hashes and the exact rule. Each qualifying
record retains every parent-owned supplier row's raw availability and presentation.

This variant has not been performance-tested. Its next analysis must use net
calendar-time portfolios, matched controls and the disclosed search history.
Do not describe supplier-classification tests as proof of a trading edge.

## Subsequent performance study

The 2026-10-03 exploratory timing study has now evaluated this strict rule. See
`results/strict_timing/1b141b2d696b/RESULTS.md` for all entry/exit metrics, dated trades
and omission diagnostics. Observed positive windows were not statistically
significant and their profits were dominated by AMRX; no verified edge was found.
