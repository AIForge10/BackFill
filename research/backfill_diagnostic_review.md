# Backfill: exploratory diagnostic review

Date: 2026-10-03. Branch: `research/backfill-diagnostic-review-20261003`.
Written after the primary and existing exploratory results were inspected.
This is an exploratory research review, not a replacement preregistration.
The original primary hypothesis and its result must remain visible.

## What was examined

Read the completed in-sample primary bundle `results/backfill/222584aadc36`,
the existing `results/exploration_grid.csv` and `results/exploration_positions.csv`,
their research specifications/code, the current owner map and engine/cache code.
Loaded and validated only `data/raw/prices/is`, ending 2024-09-30.
No new strategy backtest, price acquisition, map edit, configuration change or
holdout inspection was performed. The ticker-map approval request remains pending.

The existing scan proposes 30 cells (three roles, two company classes, five
horizons); its CSV contains 25 populated cells. No populated cell meets its
Holm-adjusted p < 0.05 and minimum-ten-events criterion. Those calculations are
exploratory and have methodological limitations described below.

## Observed leads and their limitations

All percentages below are descriptive gross endpoint stock returns minus the
entry beta times the hedge's endpoint return. These are not net portfolio returns.

| Observation | Result | Interpretation |
|---|---:|---|
| All primary winner lots, 60 sessions | -4.62%; 19 lots | Original direction is negative |
| Injectable-product winner lots, 60 sessions | +2.36%; 10 lots | Superficially promising product grouping |
| Same injectable group, one observation per ticker/entry date | -0.36%; 8 exposures | Positive mean depends on repeated exposures |
| Generic-maker winner events, 5 sessions | +0.66%; 8 events | Small exploratory lead, not reliable evidence |
| Generic-maker winners minus same-event controls, 5 sessions | +1.36%; 8 paired events | Descriptive contrast; no valid significance claim |
| Generic-maker winner events, 20 sessions | -4.86%; 8 events | Nearby longer horizon reverses direction |
| Generic-maker winner events, 60 sessions | -15.97%; 8 events | Does not support the smaller-maker rescue story |
| Generic-maker controls, 5 sessions | +1.44%; 24 events | Positive sector-peer returns do not establish supplier alpha |

Three Pfizer injection events enter on 2016-03-07 and share the same +13.23%
60-session endpoint hedged return. Separate event lots are legitimate accounting,
but they are not three independent stock-return observations. De-duplicating
for this diagnostic changes the observation weighting; it does not revise the
primary's actual portfolio accounting.

There are 16 unique ticker/entry-date exposures among 19 primary executed lots,
on 14 distinct entry dates. Pfizer supplies ten lots and Teva six. Amphastar has
zero primary winner rows: 23 controls and one nonwinner in the prepared ledger.
Its revenue example therefore has not been directly tested as an available
winner in this primary sample. Absence could reflect evidence coverage, selection
rules or availability; it does not justify classifying it as a winner without evidence.

Dropping Pfizer makes the mean of retained winner lots worse (-13.86%). Dropping
Teva changes the retained-lot mean to +0.25%; dropping Teva and Amneal produces
+3.58%. These are outcome-conditioned attribution calculations, not eligible
stock-selection rules or independent tests. They do not establish that those
companies' movements were random, or caused by earnings/litigation.

## Data and inference audit

- Ten cached symbols passed the repository's file-hash and bar-validation checks;
  all cache dates end by 2024-09-30. All fingerprinted primary input/code files
  still match that bundle's recorded hashes.
- Seven equity/ETF series use Webull. TEVA and RDY use documented Yahoo fallbacks;
  the market calendar uses Yahoo. Failed Webull cross-check numbers remain in
  the fallback provenance and do not describe the replacement series' quality.
- Integrity and cross-vendor checks do not prove economic correctness. Recorded
  exclusions remove seven HSP/MYL lots, so delisted-security coverage remains a
  real limitation. Cross-vendor correlation also cannot prove point-in-time
  corporate-action treatment or correct security identity by itself.
- Six executed winner lots have uncertain listing dates. Entry is a median nine
  calendar days after the first observed FDA listing (range 1-32 days), and first
  archived observation need not equal the first actual public announcement.
  The existing data are weak for a next-day attention-effect claim.
- The grid averages returns within events, then uses independent-event t-tests.
  Overlapping holds, repeated companies and simultaneous exposures violate that
  independence assumption. Holm correction does not repair invalid input p-values.
- The grid uses gross endpoint hedge returns, omitting costs, hedge carry,
  portfolio caps and daily portfolio accounting. It cannot establish executable
  net profitability. The generic-maker flag is not a measure of company size,
  injectable specialization or revenue materiality.
- The secondary short diagnostic computes `-long_daily_return - borrow`. The
  long return already subtracts transaction costs and carry; negating it adds
  those charges back. This is not valid short-side net accounting. A real short
  implementation must reverse exposures/P&L and subtract its own costs, with
  financing and borrow assumptions stated. No such corrected short was run here.

## Recommended direction: material product exposure and constrained competition

The defensible mechanism to investigate is product-level revenue redistribution,
then whether that redistribution is large enough and slow enough to affect the
listed parent's stock. Do not choose a company because its historical return
was favorable. Do not equate a generic-maker label with meaningful exposure.

Amphastar's August 7, 2024 earnings release reports epinephrine revenue of
$27.941m versus $16.714m, attributes growth to other suppliers' shortages, and
attributes lidocaine/phytonadione weakness to competitors returning. This supports
a revenue mechanism; it does not demonstrate predictable abnormal stock returns.

Source: https://www.sec.gov/Archives/edgar/data/1297184/000129718424000045/amph-20240807xex99d1.htm

Candidate exploratory hypothesis, NOT tested or confirmed:

> In sterile-injectable shortages, an available manufacturer's next reported
> product sales improve more when that product was already material to its listed
> parent's revenue and competing suppliers were documented as disrupted. Any
> abnormal stock-return effect should increase with that pre-event materiality.

Implementation should stay basic:

1. Build an evidence table before any further return comparisons: event/product,
   formulation, dated owner, availability quotation, disrupted competitors,
   filing publication timestamp, trailing product sales, consolidated sales and
   dated sources. Group observations by ingredient/formulation and listed parent.
2. Use only filings/catalogues public before the decision time. Calculate product
   revenue / parent revenue as a continuous feature where disclosed. Missing
   product revenue is unknown, not zero and not an estimated invented value.
   Record own allocation/capacity uncertainty instead of treating availability as
   proof of spare capacity. Historical owner-map additions need independent evidence.
3. Define specialist status from contemporaneous business descriptions/product
   catalogues, before viewing its return slice. AMPH/Hikma and other manufacturers
   are research candidates only where dated evidence qualifies them. Include every
   qualifying company, including losers; do not hard-code winners discovered here.
4. First test product-sales growth against prior product history and appropriately
   matched non-shortage products. An earnings report is an outcome, never a
   backdated feature. Positive sales evidence is not automatically a trading edge.
5. For a stock-return test retain 60 sessions as the earnings-lag main horizon;
   report 20/120 as already examined sensitivities. The small positive five-day
   slice is not a reason to redefine the main test. Net daily calendar-time
   accounting, contemporaneous controls, concentration diagnostics and dependency-
   aware uncertainty are required. Calendar block-bootstrap/HAC and company
   sensitivity checks should be reported with the actual small sample limits.
6. Disclose every existing search and this post-result refinement. Preserve the
   registered primary for its planned single holdout evaluation. Do not substitute
   this unconfirmed hypothesis into that run or treat already-inspected in-sample
   dates as new validation data.

An accurate note can say: "The broad shortage indicator was unsupported. We
identified limited product-exposure coverage and developed a narrower mechanism
based on pre-event revenue materiality." It cannot yet say the narrower mechanism
works or has an amazing correlation.

## Reviewed artifact hashes

| Artifact | SHA-256 |
|---|---|
| Primary winner costs1 metrics | `4fb6fa70fe4042199815287ac0dcdd81fa7477cbcd430096da84f1954a96129b` |
| Existing exploration grid | `8569d21902b059023f13927fb50dcf7dd7e5ae77d1440cfafccf655353839892` |
| Existing exploration positions | `42c3ac1299ef0e57598352a47454e0459f98f29b9f4045fd13013924247710d6` |

The official competition page could not be retrieved during this review. Track
requirements are taken from the user's supplied brief, not independently verified.
