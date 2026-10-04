# Hypothesis: Backfill (Channel-Fill Window)

**Edge source:** Procurement friction and limited attention

## Hypothesis

We expect **listed generic and sterile-injectable drug manufacturers** with available supply to **outperform their market benchmark** over a **5-session window starting 20 trading sessions after an FDA shortage notice becomes public.**

The edge exists because **hospital formularies and group purchasing organizations (GPOs) take roughly 3–4 weeks to reallocate procurement quotas and execute secondary purchase orders.** Investors overlook the initial FDA notice, and volume/pricing revaluation concentrates as those channel purchase orders clear. The edge persists because linking a shortage to the specific surviving supplier requires point-in-time detail records that the FDA actively deletes upon resolution.

If true, we should see **positive index-hedged returns for strictly available suppliers during this execution window, decaying rapidly at longer holding periods as manufacturing constraints and sector-wide pricing pressures reassert themselves.** It fails if placebos match the return or if transaction costs eliminate the excess return.

## Economic reasoning

When a drug enters shortage, hospitals cannot switch overnight; contracting and wholesaler reallocations typically take 15–20 trading sessions. Once purchase orders shift, the remaining suppliers capture an immediate volume and pricing surge. However, because generic drug manufacturing carries high fixed costs, capacity bottlenecks, and secular price erosion, holding beyond this short window exposes capital to broader industry headwinds and hedge drag.

## Definitions

- **Event:** a product first appears as "Currently in Shortage" on an archived FDA Drug Shortages page, after at least 180 days of absence.
- **Information date:** the later of the first public shortage snapshot and the archived supplier detail capture.
- **Winner:** a listed company where all recorded presentations for that product are confirmed available, unallocated, and non-empty on the latest archived page dated on or before entry.
- **Entry date:** 20 trading sessions after the first eligible session following the information date.
- **Holding period:** 5 trading sessions from entry.

## Primary test

Long each qualified winner at the entry date close, hedged with SPY using a rolling 250-session beta ending before entry, held for 5 sessions. Results are evaluated as an independent-lot calendar-time portfolio, net of transaction fees and hedge carry.

## Predictions

1. Strictly available winners earn positive hedged returns over the 5-session window net of costs.
2. Holding periods beyond 5–10 sessions show steep performance decay due to sector headwinds and hedge carry.
3. Placebo generic manufacturers absent from the shortage page show no equivalent concentrated excess return.

## Test rules

- **In-sample:** June 2014 to September 2024. **Out-of-sample:** October 2024 to October 2026, held strictly frozen and run once.
- **Costs:** Stock 10 bps, hedge 2 bps per side, plus 50 bps/year hedge carry. Evaluated at baseline and doubled costs (2x).
- **Caps:** 8% single-name cap, 30% country cap, 50% sector cap, 150% gross, 25% net exposure.
- **Every variant tried** is logged in `results/variants_log.csv` and disclosed.
