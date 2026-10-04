# Dashboard verification · 2026-10-04

Implemented and checked locally; not deployed publicly. No real backtest or
holdout evaluation was triggered by this UI work.

| Behavior | Observed check |
|---|---|
| Candidate metrics reflect saved outputs | 0.5346 normal costs, 0.4946 doubled; 8 lots / 7 events |
| Vendor controls use separate results | Webull-only doubled-cost Sharpe displays 0.59 |
| Basket is honestly classified | Reported 0.6675; no invented daily equity or substituted Webull run |
| Original negative result stays visible | Historical-primary Sharpe displays −0.59 |
| Frozen source integrity is calculated | 8/8 matching SHA-256 hashes; changed-file fixture becomes mismatch |
| Evidence is inspectable | Search, pagination, empty search, archive link, drawer and Escape dismissal |
| Downloads work | Valid NAV, lots, trades, events CSV and manifest/freeze JSON attachments |
| Read boundaries hold | Arbitrary file paths, traversal and invalid scenario parameters are rejected |
| Optional feed is explicit | No configuration shows disconnected state and no invented observations |
| Tiger queries preserve provenance | Fixtures verify read-only session, source, time, ingestion time and stale quotes |
| Errors preserve credentials | Simulated driver exception containing a secret does not expose it in JSON |
| Rezt rendering works | Desktop light/dark, tablet 768px and mobile 390px, reduced motion |
| Browser runs cleanly | No console errors; no external fonts or asset requests; no page overflow |

Automated checks: 27 existing synthetic research tests plus 12 dashboard tests.
The headless browser check exercised localhost:8080 and saved screenshots under
the gitignored `outputs/dashboard-qa/` directory. Browser images were visually
inspected in both themes.

The real Tiger Data service has not been tested: no connection was configured.
Schema creation and ingestion are explicit operator actions. A database with
the documented schema, a reader credential and real vendor/FDA observations
is required for a genuine live feed. PostgreSQL fixtures do not establish
cloud connectivity or vendor-price correctness.
