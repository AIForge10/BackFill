# Rule: shortage events in the 2024-09 → 2025-09 archive gap

*Written before any gap-year CSV copy was parsed. Applied only inside the frozen holdout run.*

## Why
From about 2024-09-06 to 2025-09-05 the FDA list page redirected to a JavaScript app whose archived
copies contain no shortage rows. The FDA's CSV export (`Drugshortages.cfm`) kept being archived:
17 distinct copies captured 2024-10 → 2025-08, stored in `data/raw/csv/` and parsed by
`src/03b_parse_fda_csv.py --final`.

## Validation (in-sample copies, 2024-04 → 2024-09)
- Drug-name keys shared with the HTML pages: 89% (259 of 291).
- FDA Initial Posting Date vs our archive-based event date: 5 of 5 matched events within 0–14 days
  (median 2 days).
- Supplier availability, same drug and company within 7 days: 93% agreement (2,490 of 2,668).

## Rule
- **Event:** a coarse_key whose rows show `Status = Current` with an **Initial Posting Date** inside
  the gap (2024-09-07 → 2025-09-04), after at least 180 days without Current status in all sources
  (HTML snapshots and CSV copies), as in the primary.
- **Public date:** the Initial Posting Date (the FDA published it that day).
- **Dating months without a copy:** a drug first posted in a month with no CSV copy (2024-10,
  2025-04, 2025-05) is still dated exactly, because later copies keep its Initial Posting Date.
- **Supplier evidence:** the first capture on or after the public date and within 30 days (the
  primary's window) from either source: a CSV copy, or an archived detail page for the drug (parsed
  by `04_parse_details.py --final`). Detail pages were archived every gap month (e.g. 1,060 in
  2025-04). No capture in the window → the event is recorded as having no evidence.
- **Trade-ready time:** the later of the end of the public date and the copy's capture timestamp, so
  nothing is used before it was observable.
- **Roles and owners:** the same availability rules, dated owner map and winner definitions as the
  primary, using the CSV's Company Name, Presentation and Availability Information.
- **Event dating source:** inside the gap, CSV Initial Posting Dates; outside it, the HTML list pages
  as in the primary. Each event's supplier evidence is a single capture (CSV copy or detail page),
  never a mix.

## Coverage check (file timestamps only; no holdout content opened)
- **Holdout (2024-10 → 2026-10):** every month has supplier evidence (detail pages each month).
  Months without a dating source (2024-10, 2025-04, 2025-05) are dated through later CSV copies.
- **In-sample:** months without a list snapshot (2014-09, 2015-12, 2016-02, 2018-10/11, 2019-02 →
  2019-04) are the known archive gaps, already handled by the `date_uncertain` flag. Months without
  supplier evidence are mostly 2015–2018, when the archive rarely captured detail pages.
