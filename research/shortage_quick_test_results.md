# Drug-shortage quick test (exploratory, 2026-10-03)
Data: openFDA drug shortages (1,587 records; only 19 'Resolved' kept -> survivorship).
100 drugs currently in shortage; 74 have a listed maker. Events = company x shortage first-post date.
Role: W = company lists the drug 'Available' (competitor in shortage); L = company 'Unavailable/Limited'.
Benchmarks: XLV (US), ^CNXPHARMA (India), ^FTSE, ^GDAXI, ^SSMI. Events before 2024-10-01 only; 2012 placeholder dates excluded.

Generic makers:
W n=76: [0,5] +0.6% (t 0.69) | [0,20] +1.3% (t 0.96) | [0,60] +1.6% (t 0.72) | [0,120] +2.8% (t 1.10)
L n=34: [0,5] -1.1% (t -1.17) | [0,20] +1.3% (t 0.58) | [0,60] -0.8% (t -0.33) | [0,120] +2.8% (t 0.70)
Big pharma placebo: W n=21 [0,60] -2.5% (t -1.39); L n=5 (too few)
Verdict: direction matches hypothesis for winners; nothing statistically significant; sample small and survivorship-biased.
Caveats: availability label is today's snapshot (lookahead); ~40 cells tested.
