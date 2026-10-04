# FDA shortage backtest — what changed in v5 / v6, and how to talk about it

*Shareable summary. Written 2026-10-04. All numbers in-sample (2014-06-01 → 2024-09-30,
10.32 years). The Oct 2024 – Oct 2026 holdout has not been opened.*

---

## 1. TL;DR

Three different questions were run, and they give three different numbers. Most of the
confusion in earlier conversation came from quoting one number as if it were another.

| # | What it is | Sharpe | Status |
|---|---|---|---|
| A | **v3 long-only** — buy the specialists after a shortage listing | **0.218** | the registered claim |
| B | **v5 long/short, event-timed** — long specialists / short the same pages' generic makers | **0.300** | meets nothing; honest answer to "does the shortage help?" |
| C | **v6 segment spread** — long specialists / short a *constant* basket of generics, hedged | **0.801** | **target 0.53 MET**, but it measures a different thing |

**If someone quotes 0.801, ask them which of the three they mean.** They are not
interchangeable and C is not evidence for the shortage hypothesis.

---

## 2. The one-line difference between B and C

> **B enters and exits the short leg with each shortage event. C never turns it off.**

| | B (v5, event-timed) | C (v6, segment spread) |
|---|---|---|
| Long leg | v3 specialist winners | *identical* |
| Short leg | the 4-5 generic makers **only during event windows**, mirroring **711 separate lots** | the same 4 names, **held continuously**, equal weight, rebalanced monthly |
| Short turnover | **7.70×/yr** | **~124 rebalances in 10 years** |
| Short trading cost | **0.637 %/yr** | **0.055 %/yr** |
| Hedge | mirrors the placebo's own hedges | explicit β×SPY, β mean 0.91 |
| Sharpe | 0.300 (0.203 on the other bundle) | **0.826 / 0.801 at 50 bp borrow** |

Why C works better: it is the *same economic view* (generics underperform specialists)
without paying for 711 round trips.

---

## 3. The bug that forced the split — the "mirror error"

This is the most important technical change and it applies to **every** long/short number
produced before 2026-10-04.

**`winner − placebo` is a valid *comparison* of two long books. It is not the return of a
portfolio you can hold**, because a short leg must also pay its own trading costs.

```
true portfolio = (gross_w − c_w)  +  (−gross_p − c_p)
sign-flipped    = (gross_w − c_w)  +  (−gross_p + c_p)      <- wrong by 2 × c_p
```

Worked example, one trade — target buys at 100, sells at 110, 10 bp a side:

| | result |
|---|---|
| target's net | **+9.80 %** |
| an identical short's net | **−10.21 %** = −(+9.80 %) − 2×(0.20 %) |
| what sign-flipping gave us | −9.80 % → **0.41 % too favourable** |

Measured from the data (cost at 1× = `return_1x − return_2x`):

| leg | cost drag at 1× |
|---|---|
| winner (long) | 0.218 %/yr |
| placebo (short) | **0.637 %/yr** |
| **correction applied to B** | **−1.275 %/yr** |

**Effect: 0.601 → 0.300.**

**What is NOT affected:** the `WIN-PLACEBO` HAC p-values written into the repo's reports
(e.g. p = 0.047) remain correct *as tests of "do the winners beat the placebo"*. They
become wrong only if read as portfolio returns.

---

## 4. What 0.801 is actually made of

Decompose C's short leg over the window:

| component | Sharpe | CAGR |
|---|---|---|
| short basket alone, constant notional, **no hedge** | **0.083** | **−1.10 %** |
| hedge alone (long β × SPY) | 0.714 | +11.33 % |
| both | 0.698 | +13.00 % |

Per name, 2014-06 → 2024-09: **BAX +12.8 %, TEVA −61.8 %, VTRS −73.2 %, PRGO −77.4 %**
against **SPY +258.2 %**.

The basket's **geometric** fall (nav 1.00 → 0.56) was largely *variance drag* — its
**arithmetic** mean was only ≈ −0.9 %/yr, so a constant-notional short of it **loses**.
The profit comes from the hedge: **being long US equities while short generic pharma.**

> **C measures the 2014–2024 spread of the market over generic pharma. It does not
> measure the effect of an FDA shortage listing.**

Correct sentence to share: *"Long sterile-injectable specialists against a short in
diversified generic makers returned Sharpe 0.80 over 2014–2024 in-sample. The event-timed
version of the same trade returns 0.30."*

Incorrect: *"the FDA shortage strategy has Sharpe 0.8."*

---

## 5. Robustness of C (all runs reported, none selected)

| variant | combined Sharpe |
|---|---|
| all four names | **0.826** |
| drop BAX | 0.754 |
| drop PRGO | 0.678 |
| drop TEVA | 0.873 |
| drop VTRS | 0.737 |
| other v3 bundle (`63a8ac16ae18`) | 0.797 |
| 2× costs | 0.818 |
| 50 bp / 200 bp borrow | 0.801 / 0.725 |

Every omission clears 0.53, so it is not a single-name artefact. An independent re-derivation
of the short leg (naive daily equal-weight, no NAV accounting) correlates **0.985** with
the engine-accounted path.

---

## 6. Multiplicity — please include this when sharing

**21 variants** have now been declared (`results/variants_log.csv`).

- Bonferroni bar: p < 0.05/21 = **0.0024** → required **Sharpe ≈ 0.96** over 10.32 years.
- C scores 0.801 (HAC p = 0.0027) → **does not clear the bar.**
- C is also **adaptive**: it was designed after B failed the same 0.53 target. An
  in-sample pass is therefore **descriptive only, not a discovery.**

No number produced today is significant after multiplicity correction.

---

## 7. Specific changes made

### New files (untracked, nothing committed or pushed)

| file | purpose |
|---|---|
| `docs/DECL_v5_long_specialists_short_generics.md` | v5 declaration **+ Amendment A** (the mirror error, written during implementation) |
| `docs/DECL_v6_specialist_vs_generic_spread.md` | v6 declaration written **before** the code, **+ Results section appended after** |
| `src/07_long_short.py` | builds B: reads the paired books, applies the `−2 × m × c_p` correction, reports borrow stress |
| `src/08_segment_spread.py` | builds C: the short basket, β-hedge, costs, combined book, borrow stress |

### Earlier pipeline fixes (now in commit `18b72a5`, swept in by another session's snapshot)

| file | change | why |
|---|---|---|
| `backfill/events.py` | `window_days` accepts **180** | allows a 180-day capture window variant |
| `backfill/pipeline.py` | declares `capture180`, `capture180_markets` | same |
| `backfill/prices.py` | drop all-null Yahoo holiday placeholder rows, audited as `dropped_empty_rows` in the manifest; partial nulls still fail | Yahoo returns rows of nulls on exchange holidays, which previously killed the fetch |

### New outputs

```
results/backfill/060685c5d6f5/v3_injectable_basket/
  ├── long_short/costs{1,2}/        # B: equity.csv + metrics.json
  └── segment_spread/costs{1,2}/    # C: equity.csv + metrics.json
```

### Deliberately NOT changed

`backfill/engine.py`, `strategies/backfill.py`, `backfill/settings.py`, `config.py`,
`backfill/analysis.py` — untouched. **22 unit tests still pass.** Both new scripts are
pure *reporting*: they read existing books and write new directories. No engine, no
strategy, no settings logic was modified, so no previously recorded result moved.

---

## 8. Data — searched, none found

| source | result |
|---|---|
| Webull OpenAPI | HTTP 417 — blocked on this network |
| Stooq | HTTP 404 for `spy.us`, `hsp.us`, `myl.us`, `lci.us` |
| Yahoo / yfinance | live tickers OK; **EMPTY** for `HSP, MYL, AKRX, LCI, TLGT, IPXL, ENDP, SGNT` |
| Wayback FDA archive | index starts **2014-06-22** — sample cannot be extended backward |

Two consequences to state up front:

1. **The survivorship gap cannot be closed here.** The long side holds only names that
   survived; this biases results **upward**.
2. **10.32 years is the entire sample.** t-stats cannot be improved by extending the period.

---

## 9. Where things stand

- `data/processed/backfill/selection.json` (commit `7026bb5`) selects **`v3_injectable_basket`**
  as the OOS candidate, bundle `9e879a24178a`, net Sharpe **0.107**, placebo p **0.047**.
- **The OOS run has not happened yet** — zero runs with `final: true`. The holdout is intact.
- Nothing has been committed or pushed by this work; the four new files are local only.

## 10. Reproduce

```bash
python src/07_long_short.py --bundle results/backfill/060685c5d6f5 --variant v3_injectable_basket
python src/08_segment_spread.py --bundle results/backfill/060685c5d6f5 --variant v3_injectable_basket
```
