# Declaration v5: long specialists, short the generic makers (the v3 differential)

**Written 2026-10-04, before this construction was implemented as a portfolio.**
Uncommitted by request (no commits, no pushes). Local file mtime is the only proof of
order; if a verifiable timestamp matters, commit this file before running `src/07_long_short.py`.
It does not replace `HYPOTHESIS.md` (v1) or `PREREG_v3_injectable_basket.md`.

## Disclosure — what is already known (read this first)

**The in-sample result of this construction is already visible and has been seen.**
Every run writes `winner_minus_placebo_costs{1,2}.csv` and `comparison_costs{1,2}.json`.
For the latest `v3_injectable_basket` bundle (`060685c5d6f5`) that difference series is:

- HAC(60) t = +1.99, **p = 0.0465**, mean +2.853 %/yr
- daily-difference Sharpe **0.601** (computed from the same CSV before this document was written)

For the earlier v3 bundle (`63a8ac16ae18`): t = +1.50, p = 0.135, Sharpe 0.508.

So this declaration does **not** create a fresh in-sample test. It converts an
already-seen difference into a properly accounted portfolio with its own metrics,
cost levels and borrow stress. **Its only untouched test is Oct 2024 – Oct 2026.**

Also already seen and must be disclosed alongside any v5 number: **20 variants** now
exist (`primary` + 19 labels in `results/variants_log.csv`). The corresponding
Bonferroni bar is p < 0.05/20 = **0.0025**, i.e. t ≈ 3.03 over 10.32 years, i.e.
**Sharpe ≈ 0.94**. Nothing in this repository reaches that.

## Hypothesis

Listed **sterile-injectable specialists** outperform listed **diversified generic makers
that the same shortage does not name**, over the 60 trading sessions after the FDA first
lists a injectable shortage, because hospitals cannot substitute an injectable and the
few remaining makers gain volume and pricing power, while a diversified generic maker's
one-product exposure is immaterial.

This is the cross-sectional form of the registered claim in `HYPOTHESIS.md`
("*no equivalent effect for the placebo group*"). It is equivalent to
`winner − placebo`: the market and sector factors cancel, leaving the
specialist-vs-generic spread.

## Rules (fixed now)

- **Long leg:** exactly `v3_injectable_basket`'s winner book — date-only injectable
  events, US specialist basket, `event_weight` 0.10, hold 60 sessions, 8 % name cap.
- **Short leg:** exactly v3's placebo book — the same events' listed US generic makers
  that the FDA page does not name — held short.
- **Sizing:** **gross-neutral**: $1.00 long, $1.00 short, net $0.00, gross 2.0.
  ~~Portfolio daily return = `winner_daily_return − placebo_daily_return`.~~
  **See Amendment A below — this line was wrong and was corrected during implementation.**
  Both books are run by the existing engine, so both legs already carry their own
  fills and beta hedges. Nothing in `backfill/engine.py` changes.
- **Costs:** report 1× and 2×, using the existing paired CSVs from each level.
- **Short borrow:** not present in the books. Stress at **0 / 50 / 200 bp per year**
  on the $1.00 short notional and report all three. Availability and recalls are
  **not** modelled — the short leg is 688 small-cap generic positions and a real fund
  could not hold all of it.
- **Metrics:** repository convention — `annualized_return` = CAGR of the combined NAV,
  `sharpe` = mean/std × √252 of the daily difference, `max_drawdown` on the combined
  NAV, HAC(60) two-sided t/p via `backfill.analysis.mean_inference`.
- **Period:** in-sample only, 2014-06-01 → 2024-09-30. The holdout stays shut.

## Success criterion

Set by the requester: **Sharpe > 0.53**, at 1× costs with borrow ≤ 50 bp/yr.
The HAC p-value is reported regardless of whether the Sharpe target is met, and a pass
on the Sharpe target alone is **not** a claim of significance.

## Data — searched, nothing more exists

| Source | Result |
|---|---|
| Webull OpenAPI | HTTP 417 — blocked on this network (recorded in every manifest) |
| Stooq | HTTP 404 for `spy.us`, `hsp.us`, `myl.us`, `lci.us` |
| Yahoo/yfinance | works for live tickers; **EMPTY** for `HSP, MYL, AKRX, LCI, TLGT, IPXL, ENDP, SGNT` |
| Wayback FDA archive | index starts **2014-06-22** — the sample cannot be extended backward |

Consequences, recorded so they cannot be discovered later:

1. **The survivorship gap cannot be closed here.** The long side holds only names that
   survived; this biases results **upward**. The true spread is likely smaller than measured.
2. **10.32 years (2014-06 → 2024-09) is the entire sample.** No additional history is
   obtainable, so t-stats cannot be improved by extending the period.
3. Oct 2024 – Oct 2026 remains the only untouched data and is reserved for **one** final run.

---

## Amendment A — the mirror was wrong (written during implementation, before results were reported)

Implementation (`src/07_long_short.py`) established that a short leg **cannot** be
obtained by sign-flipping a cost-loaded long return, because the short must also pay
its own trading costs.

| | long leg | short leg |
|---|---|---|
| true P&L | `gross_w − c_w` | `−gross_p − c_p` |
| sign-flipped comparison gives | `gross_w − c_w` | `−gross_p + c_p` |
| **error** | — | **2 × c_p in your favour** |

Worked example, one trade — target buys at 100, sells at 110, 10 bp a side:
target nets **+9.80 %**; an identical short nets **−10.21 %** = −(+9.80 %) − 2×(0.20 %).
The sign-flipped version would have reported −9.80 %, i.e. 0.41 % too favourable.

`c_p` is measured from the data rather than assumed: `return(1×) − return(2×)` isolates
exactly the cost charged at 1×, because the 2× run doubles that charge and nothing else.
Measured cost drag — winner **0.218 %/yr**, placebo **0.637 %/yr** (consistent with the
placebo's 7.50×/yr turnover at 10 bp a side).

**Corrected portfolio return = `difference − 2 × m × c_p`.**

### Consequence for what was declared above

- `winner − placebo` remains a **valid statistical test** of "do the specialists beat
  the generic makers" — it compares two long books, each paying its own costs. The
  HAC p-values reported throughout this repository are unaffected by this amendment.
- It is **not** the return of a portfolio you can hold. As a portfolio, the number
  changes materially (see `src/07_long_short.py` output).
- The success criterion (Sharpe > 0.53) is unchanged and is now evaluated on the
  **corrected** series.

Nothing else in this declaration was altered after seeing results.
