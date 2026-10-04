# Strict supplier holdout: metrics unavailable

Checked 2026-10-03. Period: 2024-10-01 through 2026-10-01.
This is a data-readiness audit, not a completed return evaluation.
No holdout prices were downloaded or loaded, no holdout returns were calculated,
and the canonical one-attempt lock was not reserved.

| Fixed exploratory comparison | With AMRX: eligible signal events | Without AMRX: eligible signal events | Return / Sharpe / drawdown |
|---|---:|---:|---|
| Wait 20 sessions, hold 5 | 0 | 0 | Unavailable |
| Immediate entry, hold 250 | 0 | 0 | Unavailable |

Zero signal events cannot confirm or reject either timing rule. It is not a
zero-return strategy and no performance metrics should be fabricated.

## What the archive contains

All 55 holdout list snapshots parse successfully, from 2025-09-06 through
2026-10-01. Parsed 8,189 supplier captures into 49,579 presentation rows.
There is no list coverage between 2024-09-06 and 2025-09-06.
The existing candidate builder detects 76 apparent holdout events: 72 at the
first returning snapshot and four later. Its US primary ledger has 61 winner
positions across 39 events, all assigned 2025-09-06 as public_date. That date
is not evidence of a first public shortage announcement.

Before excluding the archive-gap observations, 33 US positions across 26
apparent events meet the all-presentations-available definition; 31 positions
remain without AMRX. Every one is dated to the first post-gap snapshot.
The FDA's own archived date-first-posted field confirms none of their selected
supplier captures lies within 30 days of its posted date. For example,
lidocaine's page reports 2012-02-22, AMRX dexmedetomidine 2020-04-10, and AMRX
methylprednisolone 2021-12-15. The most recent posted date in that group is
VTRS methylphenidate film, 2025-02-28, but its selected capture is 2025-10-06,
220 days later. These are not usable announcement-timed holdout observations.
First-posted dates can refer to original shortages rather than recurrences;
they do not independently establish every recurrence date.

All four later events fail supplier-evidence requirements: isocarboxazid,
ifosfamide and pentostatin have no indexed matching supplier capture within
30 days; sodium chloride's only matching indexed capture is a discontinuation
page. Their dates and reasons are in the accompanying attrition table.

The pre-return frozen strict protocol conservatively excludes events first
observed after a list gap of at least 180 days. The registered primary remains
unchanged; its date-uncertain archive-gap candidates are explicitly flagged as
an announcement-timing problem, not promoted as valid confirmation.

## Preserved work

Specifications and research code were committed before reading holdout signals
at 3180a68; tested batch and FDA-only preparation were frozen at 748d4c3
(`freeze-oos`). All 31 tests passed. The original primary's hypothesis, map,
configuration and accounting code match its completed in-sample identity.
The original shared repository's holdout lock remains absent.

The in-sample timing selections were selected from a bounded exploratory grid,
not all possible timeframes. Neither is now independently validated. Their
positive in-sample returns were concentrated in AMRX; preserve that disclosure.

To obtain a defensible holdout result, recover contemporaneous shortage
announcement and supplier evidence for additional eligible events, or collect
future observations prospectively under the frozen rules. Today's FDA supply
page cannot reconstruct historical availability. Any event-date reconstruction
change must be disclosed and frozen before return evaluation. The present
archive does not support the requested four performance comparisons.

Evidence: `data/processed/strict_oos_readiness/gap_qualified_date_audit.csv`,
`post_gap_event_attrition.csv`, and `preparation.json`. Full FDA-only preparation
is preserved locally under `data/raw/oos/signals/`; vendor acquisition was not run.
