# Backfill Backtest Report — Coverage-Fix Round

**Date:** 2026-10-03 (local, uncommitted — nothing pushed)
**Scope:** two pre-declared data-coverage fixes, run as a 2×2 design, plus diagnostics.
**Bottom line:** the sample got 3× bigger (17 → 51 events, 19 → 74 positions) and the
result stayed negative. **Sharpe did not turn positive, annualized return did not turn
positive, and neither is close.** Section 7 explains what this means for the goal of
"making the numbers positive."

---

## Summary

The original report failed on 13 variants. Two of the three causes it identified were
structural (not statistical) and both are fixable from local data:

1. **`no_capture_in_window` killed 194 of 476 events.** The supplier window was only
   30 days before / 60 days after the FDA listing date, and the archived FDA crawl is
   sparse. Widening the forward window to 180 days recovers 109 of those 194 events.
2. **`subset:outside_markets` killed every non-US listing.** The primary scope is US
   listings only. Hikma (HIK.L), Fresenius Kabi (FRE.DE), Novartis (NOVN.SW) and 8 Indian
   generic makers are in the mapping but were never priced, so the `all_markets` variant
   had never actually run.

This round fixes both, runs a clean 2×2 (window × markets) so the two effects can be
separated, and reports whatever came out.

**What came out:**

| | 30-day window | 180-day window |
|---|---|---|
| **US only** | −0.56 %/yr, Sharpe −0.58 | −0.79 %/yr, Sharpe −0.52 |
| **All markets** | −0.24 %/yr, Sharpe −0.19 | −0.78 %/yr, Sharpe −0.45 |

Widening the window buys ~2× the trades but costs a **median 34-day entry delay**
(vs 9 days) — late entry is what makes it worse, not the extra data. Adding non-US
markets is the one change that clearly helps: it moves Sharpe from −0.58 to −0.19 and
adds the only positive country sleeve (India, +3.74 %/trade). It still does not clear zero.

---

## 1. What changed in code this round

Three edits, all local, all uncommitted:

| File | Change |
|---|---|
| `backfill/events.py` | `window_days` now accepts `180` in addition to `30`/`60`. |
| `backfill/pipeline.py` | Two new variants declared **before** evaluation: `capture180`, `capture180_markets`. |
| `backfill/prices.py` | Yahoo emits **all-null placeholder rows** on exchange holidays (German Unity Day, NSE holidays, Swiss holidays, 4 FX dates). These are now dropped at ingestion — dropped, never filled — and every dropped date is written to `manifest.json` as `dropped_empty_rows` so the removal stays auditable. Rows that are only *partly* null still hard-fail `validate_bars`. |

`backfill/prices.py` is the only change to the accounting path, and it does not touch a
single real price. Before the fix, 20 of 37 required symbols failed ingestion on
placeholder rows; after it, 37/37 downloaded with 0 failures.

Tests: `python -m unittest discover -s tests` → **22 tests, all pass.**

Two other sessions were active in this repository during this round (see §8). Their
edits and mine coexist; no file was overwritten.

---

## 2. Data used

- `data/processed/shortage_events.csv` — 498 events, 476 inside the in-sample window.
- `data/processed/suppliers.csv` — ~60,851 supplier presentations.
- `data/company_ticker_map.csv` — the approved team mapping (34 rows).
- `data/raw/prices/is-v4/` — **new cache built for this round**: 37 symbols, 0 failures.
  Same adjustments as every prior cache (`auto_adjust=False`, `actions=True`, adjusted-close
  total-return units, LSE prices pence→pounds). Vendor `yfinance`, because Webull is blocked
  on this network — recorded in the manifest exactly as in `is-v2`/`is-v3`.
- **Excluded, disclosed:** `HSP` (Hospira, acquired 2015) and `MYL` (Mylan, merged 2020).
  Delisted history is not retrievable from Yahoo; Webull would have had it but is blocked.
  **This is a survivorship gap and it biases the long side upward** — we are holding only
  names that survived. 7 lots in `primary` and 14 in `capture180_markets` are dropped for
  this reason and logged as `explicit_price_exclusion`.
- In-sample period: 2014-06-01 → 2024-09-30. **The Oct 2024 – Oct 2026 holdout was not opened.**

---

## 3. Hypothesis (unchanged)

> Listed generic and sterile-injectable drug manufacturers outperform their local market
> index over 60 trading days after the FDA first publicly lists a shortage of a product
> they can still supply, because investors wait for earnings instead of reading FDA supply
> notices.

`HYPOTHESIS.md` was not edited for this round. The two new variants extend axes that were
already pre-declared (`capture60` widened the window; `all_markets` was declared but could
never run without prices).

---

## 4. Strategy rules (unchanged)

Entry at the next local close after the trade-ready date (= FDA public date, or the first
archived page in the window if that comes later). Position size = `event_weight` of NAV
split across named winners (5 % per event in the primary), hedged with the local index for
60 sessions using a 250-session beta, with 10 bp per side (US) and 2 bp hedge cost.
Name cap 8 %, country cap 30 %, gross cap 1.5×. Costs reported at 1× and 2×.

---

## 5. What we ran

A **2×2 factorial**, not a parameter sweep. Every cell is one pre-declared combination of
two binary switches; nothing was tuned between runs.

| Cell | Variant | Forward supplier window | Markets |
|---|---|---|---|
| A | `primary` (re-baselined on `is-v4`) | 30 d | US |
| B | `capture180` | 180 d | US |
| C | `all_markets` | 30 d | US, UK, DE, CH, IN |
| D | `capture180_markets` | 180 d | US, UK, DE, CH, IN |

Evidence-ledger attrition:

| | included events | `no_capture_in_window` | `no_listed_available_winner` | `outside_markets` | ledger winner positions | traded |
|---|---|---|---|---|---|---|
| `primary` | 30 | 194 | 102 | 108 | 26 | 19 |
| `capture180` | 59 | 85 | 176 | 197 | 54 | 40 |
| `all_markets` | 30 | 194 | 102 | 0 | 42 | 35 |
| `capture180_markets` | 59 | 85 | 176 | 0 | 88 | 74 |

The wider window converts 109 "no capture" events into candidates; 74 of them then fail on
"no listed available supplier" (they were never going to be tradable), leaving 30 → 59
included events. `capture180_markets` crosses the project's own **50-independent-event
power bar** for the first time outside the basket: 51 events, 74 positions, 17 tickers.

---

## 6. Results

### 6.1 Main results (1× costs)

| Variant | Events | Positions | Ann. return | Sharpe | Max DD | HAC p (winner) | Placebo ann. | Placebo Sharpe | Win−Placebo p |
|---|---|---|---|---|---|---|---|---|---|
| `primary` | 17 | 19 | **−0.557 %** | **−0.584** | −6.6 % | 0.160 | +0.066 % | +0.083 | 0.140 (t = −1.48) |
| `capture180` | 36 | 40 | **−0.790 %** | **−0.523** | −9.3 % | 0.127 | −0.206 % | −0.112 | 0.316 (t = −1.00) |
| `all_markets` | 25 | 35 | **−0.241 %** | **−0.185** | −6.7 % | 0.569 | +0.306 % | +0.201 | 0.149 (t = −1.45) |
| `capture180_markets` | 51 | 74 | **−0.776 %** | **−0.454** | −10.4 % | 0.138 | −0.036 % | −0.006 | 0.139 (t = −1.48) |

**Not one cell is positive on either metric.** Reading the 2×2 as two separate effects:

| Effect | On Sharpe | On annualized return |
|---|---|---|
| Add non-US markets, 30-day window (`primary` → `all_markets`) | −0.58 → **−0.19** better | −0.56 % → **−0.24 %** better |
| Add non-US markets, 180-day window (`capture180` → `capture180_markets`) | −0.52 → **−0.45** better | −0.79 % → **−0.78 %** flat |
| Widen window, US only (`primary` → `capture180`) | −0.58 → **−0.52** better | −0.56 % → **−0.79 %** worse |
| Widen window, all markets (`all_markets` → `capture180_markets`) | −0.19 → **−0.45** worse | −0.24 % → **−0.78 %** worse |

Adding non-US listings helps. Widening the capture window helps only in combination with
the US-only scope, and hurts return in both cells — its cost is the entry lag in §6.4.
Wider books narrow the distribution (Sharpe −0.58 → −0.45 across 19 → 74 positions);
diversification shrinks the noise, it does not move the centre. No cell crosses zero.

### 6.2 Costs doubled

| Variant | Ann. return | Sharpe |
|---|---|---|
| `primary` | −0.578 % | −0.606 |
| `capture180` | −0.834 % | −0.552 |
| `all_markets` | −0.283 % | −0.218 |
| `capture180_markets` | −0.825 % | −0.490 |

Costs are not the problem. The 1× → 2× drag is 2–5 bp/yr on a book turning over 0.24–0.48×
a year. **Even at zero cost the book is negative.**

### 6.3 Where the losses come from (`capture180_markets`, 74 lots)

Mean −2.40 %, median −2.85 %, win rate 42 %.

**By country:**

| Country | n | Mean hedged 60-session return |
|---|---|---|
| **India** | 13 | **+3.74 %** |
| Switzerland | 5 | −1.26 % |
| Germany | 11 | −2.70 % |
| United States | 40 | −4.12 % |
| United Kingdom | 5 | −5.10 % |

**By name (top and bottom):**

| Ticker | n | Mean | | Ticker | n | Mean |
|---|---|---|---|---|---|---|
| AMRX | 1 | −39.7 % | | PFE | 16 | +2.3 % |
| TEVA | 12 | −11.2 % | | VTRS | 2 | +2.7 % |
| BAX | 7 | −5.3 % | | TORNTPHARM.NS | 3 | +3.5 % |
| HIK.L | 5 | −5.1 % | | APLLTD.NS | 3 | +9.8 % |
| FRE.DE | 11 | −2.7 % | | ZYDUSLIFE.NS | 1 | +34.0 % |

Two structural readings, both uncomfortable:

- **A single AMRX trade (−39.7 %) is worth more than the entire India sleeve.** The
  book's negative mean is dominated by a handful of large idiosyncratic losses, which is
  a concentration problem, not a signal problem — but concentration cannot be "fixed"
  by dropping the losers after seeing them.
- **The named parent is usually a diversified company.** Pfizer (16 lots, +2.3 %) and
  Fresenius Kabi (11 lots, −2.7 %) are not firms where one shortage moves the stock.
  This is the same observation that produced the specialist basket.

### 6.4 The cost of the wider window

Median entry lag from FDA public date to fill:

| Variant | Median lag | Mean lag | Max lag |
|---|---|---|---|
| `all_markets` (30 d window) | 14 d | 13.0 d | 32 d |
| `capture180` (180 d window) | 34.5 d | 42.3 d | 114 d |

Widening the window only admits events whose **earliest archived page** is later — so it
structurally selects for late entry. `capture180` trades 2.1× the positions of `primary`
and earns *less*. The extra 109 recovered events are not free data; they are events we are
trading up to four months after the news.

There is no route to "earlier entry": captures essentially never precede the FDA listing
date (only 39 of 476 events have any capture on or before the public date), because the
Wayback crawl starts after the FDA publishes.

### 6.5 Mirror test: short the disrupted side

The report's remaining open direction was the short side. Before building engine support
for short selling (a large change), the returns were measured directly on the existing
`disrupted` ledger rows:

| Book | n | Mean hedged | Median |
|---|---|---|---|
| Disrupted, all markets | 79 | **+5.02 %** | −0.05 % |
| Disrupted, US only | 46 | **+7.84 %** | — |
| Available, US only | 40 | **−4.12 %** | — |

**The short side does not work either.** Companies the FDA page marks as disrupted
*averaged positive* hedged returns. Long-available / short-disrupted in the US would be
−11.96 pp per event — the signal runs backwards with a large magnitude. And because the
same tickers (PFE, TEVA, BAX) appear in *both* books with opposite signs, the split is
event-specific noise, not a company or status effect.

The `v4_disrupted` pre-registration (another session's, committed before implementation)
confirmed this on real accounting: **ann −0.072 %, Sharpe −0.035, p = 0.874** — it fails
its own success criterion (which required p < 0.05).

**Consequence: the long/short matched-pair redesign is now ruled out on evidence, not on
effort.** No engine change was made, and none should be until a mechanism check explains
why disrupted names *outperform*.

---

## 7. Answer to the actual question: can Sharpe and annualized return be made positive?

Not with these data and this hypothesis, honestly. Here is every available route and what
it would prove:

| Route | Result | Verdict |
|---|---|---|
| **Coverage fixes (this round)** | −0.24 % to −0.79 %/yr, Sharpe −0.19 to −0.58 | Tried. Doesn't flip the sign. |
| **Drop the index hedge** | The book would show ≈ +8–10 %/yr purely from equity beta. | **Proves nothing.** The placebo (non-supplier generic makers) gains the same beta. Reported as `winner − placebo ≈ 0` for that reason. |
| **Drop TEVA / AMRX / BAX post hoc** | Flips the sign by construction. | **Invalid** — it is the survivorship selection the original report correctly criticized in the basket. |
| **Hold-period tuning** | Primary: hold 10 → −0.02 %, hold 20 → −0.21 %, hold 40 → −0.26 %, hold 60 → −0.56 %, hold 120 → −0.21 %. All negative. | 5 more variants, all negative. |
| **Long the disrupted side (v4)** | −0.072 %, Sharpe −0.035, p = 0.874 | Fails its pre-registered criterion. |
| **Concentrate on the basket** | `v2_specialist_basket` at hold 60: **+1.93 %/yr, Sharpe 0.67, p = 0.038** (58 pos) / +2.22 %, 0.67, 0.040 (40 pos) / +1.65 %, 0.61, 0.047 (52 pos) | **The only positive result in the project — and it is post hoc.** |
| **`v3_injectable_basket`** (pre-registered, date-only events, no supplier page) | **+0.372 %/yr, Sharpe +0.107**, p = 0.716; placebo −1.87 %; win−placebo p = 0.135 (t = +1.50) | Positive on both metrics, **nowhere near significant**. Pre-registered, so the OOS test is still clean. |

Two honest statements about the positive numbers that exist:

1. **The basket's hold matters enormously.** The same variant at hold 60 gives
   +1.65 %…+2.22 % / Sharpe 0.61–0.67 / p 0.038–0.047; at hold 10 it gives **+0.161 %,
   Sharpe 0.136, p = 0.632**. Both are in `results/variants_log.csv`. A result that flips
   from p = 0.04 to p = 0.63 on a hold-period change is not a robust finding, and the
   registered primary hold is 60 — which happens to be the passing cell. That must be
   disclosed before anyone quotes p = 0.038.
2. **Nothing here clears the multiple-testing bar.** 19 distinct variants have now been
   tried (§8). At p < 0.05/19 the required threshold is **p < 0.0026**. The best p in the
   project is 0.038. **No variant, including every positive one, is significant after
   correction for the number of variants tried.**

**What would actually settle it:** the mechanism check from the original report's own
next-steps — verify that AMPH/ICUI/AMRX/TEVA *did* post revenue surprises after these
shortages. If the revenue channel is not in the filings, no book construction will find
it, and the correct output is a negative result reported as such.

---

## 8. Full disclosure — everything tried

Counts at time of writing (recount with the snippet in §12):

- **19 distinct variant labels:** `primary`, `hold10`, `hold20`, `hold40`, `hold120`,
  `capture60`, `capture180`, `capture180_markets`, `all_markets`, `allocation`,
  `certain_dates`, `all_flags`, `v2_expanded`, `v2_specialist`, `v2_injectables`,
  `v2_primary`, `v2_specialist_basket`, `v3_injectable_basket`, `v4_disrupted`.
- **63 bundles** under `results/backfill/` — 61 completed, 2 failed.
- **62 distinct `run_id`s** in `results/variants_log.csv` (495 lifecycle rows; 3 rows have
  unparseable `notes` and are excluded from status counts — worth repairing).
- The original report's "13 versions" is now **19**; the multiplicity penalty is worse
  than it was, not better.

Latest completed run per variant, 1× costs, winner book:

| Variant | Run | Pos | Events | Ann. % | Sharpe | p | Placebo ann. % | W−P p |
|---|---|---|---|---|---|---|---|---|
| `hold10` | 9a23506cd333 | 19 | 17 | −0.023 | −0.069 | 0.746 | −0.015 | 0.940 |
| `hold20` | e4c630dbb526 | 19 | 17 | −0.205 | −0.444 | 0.165 | +0.048 | 0.098 |
| `hold40` | 7dd74e827233 | 19 | 17 | −0.263 | −0.354 | 0.249 | +0.080 | 0.229 |
| `hold120` | ff36ce492386 | 19 | 17 | −0.206 | −0.153 | 0.550 | +0.332 | 0.206 |
| `primary` | 90d38999987a | 19 | 17 | −0.557 | −0.584 | 0.160 | +0.066 | 0.140 |
| `capture60` | c90bffcb5727 | 30 | 27 | −0.687 | −0.556 | 0.160 | +0.023 | 0.160 |
| `allocation` | c2244a856b71 | 20 | 18 | −0.505 | −0.493 | 0.216 | +0.151 | 0.127 |
| `certain_dates` | fb53edd8f69f | 13 | 12 | −0.523 | −0.581 | 0.175 | +0.015 | 0.197 |
| `all_flags` | d3dd06542472 | 22 | 19 | −0.641 | −0.674 | 0.112 | +0.060 | 0.108 |
| `all_markets` | 3ba4bf19d0b9 | 35 | 25 | −0.241 | −0.185 | 0.569 | +0.306 | 0.149 |
| `capture180` | 6e6b927859ba | 40 | 36 | −0.790 | −0.523 | 0.127 | −0.206 | 0.316 |
| `capture180_markets` | c0ae584eafce | 74 | 51 | −0.776 | −0.454 | 0.138 | −0.036 | 0.139 |
| `v2_expanded` | fc47e60ae3ac | 24 | 22 | −0.536 | −0.499 | 0.182 | +0.210 | 0.066 |
| `v2_injectables` | c6e0b93baf3d | 12 | 11 | −0.059 | −0.106 | 0.721 | +0.257 | 0.132 |
| `v2_specialist` | 1b0a596b60d8 | 2 | 2 | +0.020 | +0.144 | 0.618 | +0.041 | 0.667 |
| `v2_primary` | e55206b5173a | 1 | 1 | −0.016 | −0.111 | 0.517 | +0.111 | 0.104 |
| `v2_specialist_basket` | 79e49f852109 | 58 | 14 | **+1.927** | **+0.671** | 0.038 | +0.025 | 0.083 |
| `v3_injectable_basket` | 63a8ac16ae18 | 589 | 172 | **+0.372** | **+0.107** | 0.716 | −1.873 | 0.135 |
| `v4_disrupted` | 2aefa214fe67 | 47 | 41 | −0.072 | −0.035 | 0.874 | +0.212 | 0.517 |

Note `primary` was run 5× and `v2_specialist_basket` 9× (identical inputs, different code
revisions and hold periods). Only `v2_specialist_basket` and `v3_injectable_basket` are
positive; neither survives correction for 19 variants.

**Do not select a row from this table.** It is a disclosure table, not a menu.

---

## 9. Data limits

1. **Survivorship gap (material).** HSP and MYL have no retrievable history. The long side
   holds only names that survived — this biases returns **upward**, so the negative result
   here is if anything an *understatement* of how badly the raw signal does.
2. **Entry lag is structural.** Captures follow the FDA listing; median 9–34 days, max 114.
   The in-sample figure cannot be improved with the current archive.
3. **`no_listed_available_winner` = 176 events** under the 180-day window. These have a
   page and a capture but no US/listed supplier we can map — permanently untradable, not
   missing data.
4. **Vendor placeholder rows.** 20 symbols required dropping all-null holiday rows
   (audited per symbol in `manifest.json` → `dropped_empty_rows`). `^FTSE 2020-12-22`
   is the one dropped date that looks like a real trading session; it affects the UK
   calendar only and cannot create a missing-bar failure (extra dates in an equity series
   are harmless; missing ones fail loudly).
5. **Webull blocked.** All 37 symbols are yfinance. `is-v2` and `is-v3` were already
   yfinance-fallback too, so no cross-vendor inconsistency was introduced.
6. **India is the only positive sleeve (n = 13)** and it is a single-country result with
   25 bp costs, INR FX marks and NSE sessions. It should be treated as a lead, not a
   finding.
7. **Two sessions worked this repository concurrently.** Bundle counts, log rows and
   `VARIANTS` entries changed while this report was being written; recount before quoting.

---

## 10. How to read the metrics

- **Annualized return** — mean daily return × 252, *not* a compounded time-weighted return.
  On a book that is invested ~30 % of sessions it mostly measures per-active-day drift.
- **Sharpe** — mean ÷ standard deviation of daily returns × √252. Cash days count as
  zero-return days, so Sharpe here is diluted by inactivity relative to a fully invested
  fund.
- **HAC p-value** — Newey–West with 60 lags, two-sided, against zero mean. It tests
  "is the mean different from zero", **not** "is this better than the placebo". The
  placebo comparison is the `WIN−PLACEBO` row, which is a paired test on
  winner-minus-placebo daily returns.
- **Max drawdown** — worst peak-to-trough on the daily equity curve.
- **Win rate 42 %** on 74 lots with mean −2.40 % means the distribution is fat-tailed on
  both sides: two trades (AMRX −39.7 %, ZYDUS +34.0 %) are worth more than the middle 40.

---

## 11. Next research directions (ranked)

1. **Mechanism check first, before any more backtests.** Confirm from 10-Q/10-K text that
   the named suppliers actually reported revenue increases after these shortages. This is
   the cheapest test with real power to distinguish "no edge" from "wrong trade rule", and
   it cannot be data-mined. If it fails, the correct next step is to write the negative
   result up.
2. **Do not build the long/short engine.** §6.5 shows available-minus-disrupted is
   −11.96 pp in the US. The evidence says the short side is not the answer either.
3. **Fix the survivorship gap if a vendor is available.** A machine with Webull access
   could price HSP and MYL and would *reduce* the upward bias — i.e. it would likely make
   the result worse, which is the right direction to spend effort.
4. **Treat `all_markets` as the better baseline, not a finding.** It is strictly better
   than the US-only primary on Sharpe (−0.19 vs −0.58) for a mechanical reason — more
   names, no new information. Adopt it as the standing scope so future variants start from
   35 positions instead of 19.
5. **Protect the holdout.** Oct 2024 – Oct 2026 has not been touched by any of this.
   `v3_injectable_basket` is the only pre-registered positive-idea candidate that has not
   been burned in-sample, and it should get exactly one OOS run — after the mechanism check,
   and with its success criterion written down before the run.
6. **Repair the 3 unparseable `variants_log.csv` rows** and add a per-run `hold_days` and
   `code_fingerprint` column, so the basket's hold-10 vs hold-60 discrepancy (§7) is visible
   in the log itself instead of requiring an identity-file diff.

**Do not:** re-run the 19 variants with cost/horizon/flag tweaks hunting a positive Sharpe;
quote p = 0.038 without the 19-variant correction (p < 0.0026) and the hold-10
disconfirmation; drop TEVA/AMRX/BAX to flip the sign; present an unhedged run as an edge.

---

## 12. Files and reproduction

**Code changed (uncommitted, local only):**
- `backfill/events.py` — 180-day window allowed
- `backfill/pipeline.py` — `capture180`, `capture180_markets` declared
- `backfill/prices.py` — all-null vendor rows dropped + audited in manifest

**Evidence ledgers:** `data/processed/backfill/{capture180,all_markets,capture180_markets}/`

**Price cache:** `data/raw/prices/is-v4/` — 37 symbols, 0 failures, HSP+MYL excluded,
20 symbols with audited placeholder-row drops.

**Results:** `results/backfill/90d38999987a` (primary), `6e6b927859ba` (capture180),
`3ba4bf19d0b9` (all_markets), `c0ae584eafce` (capture180_markets).

**This report:** `results/BACKTEST_REPORT_coverage_fixes_2026-10-03.md`

**Reproduce:**
```bash
python src/05_events.py --variant capture180
python src/05_events.py --variant all_markets
python src/05_events.py --variant capture180_markets
python src/06_prices.py \
  --events data/processed/backfill/{primary,capture180,all_markets,capture180_markets}/events.csv \
  --cache data/raw/prices/is-v4 --vendor yfinance \
  --exclude 'HSP=Hospira acquired by Pfizer 2015; delisted history unavailable from Yahoo and Webull blocked; survivorship gap disclosed' \
  --exclude 'MYL=Mylan merged into Viatris 2020; delisted history unavailable from Yahoo and Webull blocked; no automatic VTRS alias'
for v in primary capture180 all_markets capture180_markets; do
  python run_all.py --variant "$v" --cache data/raw/prices/is-v4
done
python -m unittest discover -s tests     # 22 tests
```

**Recount the disclosure:**
```bash
python - <<'PY'
import csv, json, pathlib
rows = list(csv.DictReader(open("results/variants_log.csv")))
print("log rows:", len(rows))
print("run_ids:", len({r["run_id"].split(":")[0] for r in rows if ":" in r["run_id"]}))
print("variants:", len({r["run_id"].split(":",1)[1].split("/")[0] for r in rows if ":" in r["run_id"]}))
print("bundles:", len(list(pathlib.Path("results/backfill").glob("*/status.json"))))
PY
```
