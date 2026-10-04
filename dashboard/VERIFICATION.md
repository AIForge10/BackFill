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
| Hypothesis appears first | Hero precedes research; refined strategy and trading rules are explicit |
| Saved outcome reveal | Shows the actual case daily curve; no new evaluation request |
| Case return measures stay separate | +1.06% net hedged, −0.62% stock-only, +1.15 pp versus SPY |
| Case stress and chart controls work | Doubled costs show +0.81%; line/bar, series visibility, range and keyboard inspection pass |
| Webull-only is actual Webull data | All three price-series source hashes verified against the Webull manifest |
| Vendor mismatch stays visible | FMS Yahoo fallback disclosed; unsupported Webull-only net view is unavailable |
| Hedge accounting reconciles | Saved cashflows and daily curve endpoints equal the basket net result at both costs |
| Portfolio denominator is clear | $100,000 NAV and 5% long allocation produce about $53 net, not $1,060 |
| Strict later-period audit stays visible | 76 economic events, zero eligible trades, unavailable Sharpe; no blind OOS claim |
| First chart is market movement | Short hypothesis → actual Webull daily price-index chart, right axis and crosshair |
| Market date controls are truthful | Preset/custom ranges use recorded sessions; a weekend-only range shows no data |
| Tiger history preserves source and state | Parameterized read-only query, one vendor, chronological order, bounded history and credential-safe errors |

Automated checks: 27 existing synthetic research tests plus 19 dashboard tests
(46 total, passed). The case update's browser checks exercised localhost:8081,
including light/dark, 768px tablet and 390px mobile. Screenshots and browser
check results are at `/private/tmp/gator-case-ui-qa/` in this workspace.
The market-first layout, custom ranges and Tiger history states were also checked
in the browser; screenshots are at `/private/tmp/gator-market-ui-qa/`. The live
price rendering check used an explicitly labeled temporary QA fixture, not real
cloud connectivity. No fixture prices are saved or displayed in the delivered site.
The headless browser check exercised localhost:8080 and saved screenshots under
the gitignored `outputs/dashboard-qa/` directory. Browser images were visually
inspected in both themes.

The real Tiger Data service has not been tested: no connection was configured.
Schema creation and ingestion are explicit operator actions. A database with
the documented schema, a reader credential and real vendor/FDA observations
is required for a genuine live feed. PostgreSQL fixtures do not establish
cloud connectivity or vendor-price correctness.
