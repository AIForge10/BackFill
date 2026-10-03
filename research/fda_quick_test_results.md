# FDA inspection quick test (exploratory, run 2026-10-03)

Data: FDA Data Dashboard inspections export (342,969 rows, FY2009-FY2026).
Filtered to Drugs/Biologics/Devices, matched ~60 US-listed pharma/medtech names by regex on Legal Name.
Events: one per inspection x ticker; classification OAI / VAI / NAI. Same-ticker events within 30 days deduped.
Holdout respected: only events with (inspection end + 90d) before 2024-10-01.
Prices: Yahoo adjusted closes; abnormal return = stock - XLV. Missing prices: NUVA, MASI, HZNP, NVRO, OMI, HOLX.

## A) After the data is plausibly public (inspection end + 90 days)
OAI n=136: [0,+5] +0.18% (t 0.62) | [0,+20] +0.48% (t 0.96) | [0,+60] +0.66% (t 0.76) | [0,+120] -0.08% (t -0.06)
VAI n=983: [0,+20] -0.13% (t -0.56) | [0,+60] +0.15% (t 0.36)
NAI n=1136: [0,+20] -0.07% (t -0.33) | [0,+60] +0.20% (t 0.62)
=> No tradeable drift once the classification is public.

## B) Anchored at inspection end date (NOT public via dashboard at that time)
[0,+30] trading days: OAI -1.08% (t -1.96) | VAI -0.57% (t -2.13) | NAI +0.45% (t +1.82)
Big caps OAI: -1.74% (t -3.12); small/mid OAI: -0.45% (t -0.47)
=> Monotonic O < V < N around the inspection itself: market prices it early (483 handed over at close, disclosures, news).

Caveats: ~90 cells tested (multiple testing), clustering not adjusted, public-date proxy is an assumption,
regex matching incomplete, survivorship (delisted names missing). Must be disclosed as variants tried.
