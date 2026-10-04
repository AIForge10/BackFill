# Hypothesis: Backfill

**Edge source:** Behavioral bias (limited attention)

## Hypothesis

We expect **listed generic and sterile-injectable drug manufacturers** to **outperform their local market index** over **60 trading days** after the FDA first publicly lists a shortage of a product they can still supply, because **investors wait for earnings instead of reading FDA supply notices**, and the edge persists because **linking a shortage notice to the specific listed company that fills the gap requires point-in-time supplier data the FDA does not keep (resolved shortages are deleted).**

If true, we should see **positive index-hedged returns for available suppliers, net of costs, and none for similar companies that do not make the product.** It fails if **the placebo group shows the same return, or the effect disappears net of costs.**

## Economic reasoning

When a drug goes into shortage, hospitals must buy from the remaining suppliers. Those suppliers gain volume and pricing power, which appears in the next quarter's revenue. Example: Amphastar reported epinephrine sales up 67.2% in Q2 2024, attributed to competitor shortages.

## Definitions

- **Event:** a product first appears as "Currently in Shortage" on an archived FDA Drug Shortages page, after at least 180 days of absence.
- **Public date:** the date of the first archived snapshot showing the shortage.
- **Winner:** a listed company marked "Available" for that product on the latest archived detail page dated on or before the trade date.
- **Trade date:** the next trading session in the stock's local market after the shortage and its supplier list are both publicly visible.

## Primary test

Long each winner on the trade date, hedged with its local index (beta from the prior 250 trading days), held 60 trading days. Results are measured as a daily calendar-time portfolio, net of costs.

## Predictions

1. Winners earn positive hedged returns net of costs.
2. Placebo: similar generic makers that do not make the product earn about zero over the same dates.
3. No significant return drift in the 20 days before the trade date.

## Test rules

- **In-sample:** June 2014 to September 2024. **Out-of-sample:** October 2024 to October 2026 (the most recent 2 years), run once on the final strategy.
- **Costs per side:** US 10 bps, UK/Germany/Switzerland 15 bps, India 25 bps. Also reported with costs doubled.
- **Signals** are traded at the next session.
- **Every variant tried** is logged and disclosed in the note.

## Revision (2026-10-03, local, not a new pre-registration)

The named parent on the FDA page is usually a diversified company, so the traded book is the **listed US sterile-injectable specialist basket**, hedged with the local index for **60 sessions**. Capital is split only across specialists that have a price history. ADRs are not in the book: a diversified foreign parent does not pick up a single US shortage the way a US specialist does. A page that appears more than **60 days** after the previous archived page is not a new posting date (the 2024-09 to 2026-01 Wayback hole).
