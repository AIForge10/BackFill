# Exploratory grid (fixed before computing)

*Pushed before any cell below was computed. Exploratory: a surviving cell becomes a candidate
hypothesis that must be pre-registered and confirmed once on the untouched holdout.*

## Status
Written after the primary (winners) and secondary (disrupted) in-sample tests were both not
supported. Nothing in this grid was chosen by looking at returns of these groups and horizons.

## Universe and evidence (unchanged)
Primary events, flags, supplier-page rule and dated owner mapping; US listings; HSP and MYL excluded
(no vendor history); prices from the validated cache `data/raw/prices/is`.

## Grid: 3 roles x 2 company types x 5 horizons = 30 cells
- **Role** (from the archived FDA page): winner (Available), disrupted (unable to supply), control
  (listed generic maker absent from the page).
- **Company type** (from the map's `is_generic_maker` column, set in the seed map before any results):
  specialty generic/injectable maker (1) vs diversified major (0).
- **Horizon:** 1, 5, 20, 60, 120 trading days after entry (entry = next local close after the
  information is known). Holds must end by 2024-09-30.

## Statistic
Per position: return minus beta x SPY return (beta from 250 pre-entry sessions). Positions are averaged
within each event, then tested across events (t-test). Holm adjustment across all 30 cells.
A cell "survives" only if Holm-adjusted p < 0.05 and it has at least 10 events.
