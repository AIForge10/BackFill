# Frozen working candidate v1

This is the current **exploratory** working rule, not a replacement for the
registered primary or a certified trading edge. Read [SPEC.md](SPEC.md) first.

## Small structure

| File | Responsibility |
|---|---|
| `strategy.py` | Past-only entry/filter conditions and exact-capture counterpart audit |
| `run.py` | Frozen settings, cache/hash validation, accounting, diagnostics and replacement gate |
| `factors.py` | Offline conversion of separately acquired official factors; never stock acquisition |
| `report.py` | Read completed results and format Markdown/PDF; never evaluate returns |
| `data/processed/final_candidate/v1/` | Frozen supplier evidence, audits, factors and prior research summaries |
| `data/raw/prices/final_candidate_v1/` | Frozen licensed cache; gitignored |
| `results/research/final_candidate_v1_20261004/` | Per-attempt logs, complete outputs, current report and latest pointer |

The shared `backfill.engine` remains the accounting implementation. This package
does not change it, config, HYPOTHESIS, primary results, the original run log or
the holdout lock. Each repeat gets a separate directory; input changes fail.

## Reproduce offline

From the repository root with its installed dependencies and frozen local cache:

```sh
.venv/bin/python -m research.final_candidate.run
.venv/bin/python -m unittest discover -s tests
```

The original cache manifest hash is
`3053d3883d9dc5115c1cd8f9518df1927952e2b760c9b9bbeb4ac2a81d172da3`.
The runner verifies every quote file and input hash. It fetches no prices and
does not fall back to another vendor. The reference retains disclosed Yahoo
TEVA data; the Webull-only policy explicitly excludes those allocations.
SPY prices occupy the engine's US calendar slot, not a fabricated index hedge.

Factor CSVs and their provenance are included; no network is needed. The raw
official archives were acquired separately from the Ken French Data Library.
The parser refuses to overwrite frozen factors. They are exposure diagnostics,
not point-in-time entry inputs.

`report.py` needs pandas/reportlab and reads only the `latest.json` completed-run
pointer. It creates `output/pdf/backfill_working_candidate_v1.pdf` and the
Markdown report. PDF rendering was verified using bundled Poppler tools.

## Edit later without losing the record

1. Keep v1 files/results and the original primary. Copy the small strategy
   package and data directory into a clearly named v2 experiment.
2. Write the new condition, sample, fixed timing and acceptance gate before
   evaluating it. Explicitly label it exploratory and specify vendor policy.
3. Preserve weights before filtering; exclusions stay cash. Use only past bars
   for signals and beta, next-session execution, and explicit price omissions.
4. Create a new freeze manifest and dedicated result/log directory. Do not
   change v1's hashes, thresholds or gate to make a new result pass.
5. Compare against v1 on the same dates, sample and vendor policy, both cost
   assumptions, controls and company omissions. Retain all trials.

The current two alternatives failed the prewritten gate, so **retain
wait-20/hold-5**. A genuine improvement also needs enough independent exposures,
calibrated execution costs and genuinely unseen evidence. The already-inspected
2024-2026 period cannot provide a new blind test for this refined rule.
