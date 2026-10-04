"""Package completed results only; never rerun or select a trading rule."""
import json
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/processed/final_candidate/v1"
OUT = ROOT / "results/research/final_candidate_v1_20261004"


def pct(value, digits=2):
    return f"{value:+.{digits}%}"


def main():
    folder = ROOT / json.loads((OUT / "latest.json").read_text())["directory"]
    summary = pd.read_csv(folder / "summary.csv")
    if not json.loads((folder / "verification.json").read_text())["baseline_reproduced"]:
        raise ValueError("Cannot publish an unverified report.")
    def read(policy="reference_mix", rule="delay20_hold5", cost=1, name="metrics.json"):
        p = folder / policy / rule / f"costs{cost}" / "winners" / name
        return pd.read_csv(p) if name.endswith("csv") else json.loads(p.read_text())
    ref, web = read(), read("webull_only")
    primary = json.loads((DATA / "primary_reference_metrics.json").read_text())
    lots = read(name="lots.csv")
    capacity = read(name="capacity.csv")
    omissions = pd.read_csv(DATA / "prior_omissions.csv")
    old = omissions[(omissions.entry_delay_sessions == 20) & (omissions.hold_days == 5)]
    no_amrx = old[(old.omission_type == "company") & (old.omitted == "AMRX") & (old.cost_multiplier == 1)].iloc[0]
    capacity_bound = float(capacity.capacity_usd_1pct.min())
    amrx_fraction = float(lots.loc[lots.ticker == "AMRX", "net_pnl"].sum() / lots.net_pnl.sum())
    comparison = json.loads((folder / "reference_mix/delay20_hold5/costs1/winner_minus_control.json").read_text())
    prior = pd.read_csv(DATA / "prior_grid.csv")
    near = prior[(prior.vintage == "refreshed") & (prior.cost_multiplier == 1) & prior.hold_days.isin([1, 5, 20])]

    markdown = ["# Backfill working candidate v1 - final for current research", "",
        "**Decision: retain strict availability, entry delay 20 sessions, hold 5 sessions.** This is a post-result exploratory candidate. The original hypothesis and registered 60-session primary remain visible; this does not validate them.", "",
        f"The previously evaluated US primary had {primary['positions']} lots / {primary['events']} events, Sharpe {primary['sharpe']:.3f}, annualized return {pct(primary['annualized_return'])}, volatility {primary['annualized_volatility']:.2%}, drawdown {pct(primary['max_drawdown'])}, annual turnover {primary['annualized_turnover']:.2%}, and HAC p={primary['inference']['p_value']:.3f}. It did not support the hypothesis. Its source metrics and provenance are preserved separately as a reporting reference.", "",
        "## Exact rule", "",
        "Every FDA-listed presentation for the contemporaneous listed parent on the selected archived formulation page must be available, unallocated and nonempty. Information becomes usable after both shortage observation and supplier capture. Identify the next US session close, wait 20 additional US sessions, enter at that close, and exit five session intervals later. No SMA filter. Status is not reverified during the waiting period.", "",
        "Beta is fitted from 250 prior stock/SPY returns, ending before entry, and stays fixed. Allocate 5% per event, split before filtering or exclusions; rejected allocations stay cash. US stocks only. 8% name, 30% market, 50% sector, 150% gross, 25% absolute-net caps. De-risk after a 10% drawdown at the next session, restoring after 20 sessions. Cash return is zero.", "",
        "## Actual in-sample results", "",
        "June 2014-September 2024. Costs: stock 10bp/SPY 2bp per side plus 50bp/year hedge carry. Doubled-cost runs double both fees and carry. The historical reference uses Yahoo TEVA fallbacks; Webull-only excludes those allocations without upweighting other names.", "",
        "| Policy / rule | Lots / events | Sharpe | Sharpe x2 costs | Mean net lot | CAGR | Volatility | Max DD | Annual turnover |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for policy in ("reference_mix", "webull_only"):
        for rule in ("delay20_hold5", "below_sma60_hold5", "below_sma60_disrupted_hold5"):
            row = summary[(summary.vendor_policy == policy) & (summary.rule == rule) & (summary.cost_multiplier == 1)].iloc[0]
            stress = summary[(summary.vendor_policy == policy) & (summary.rule == rule) & (summary.cost_multiplier == 2)].iloc[0]
            markdown.append(f"| {policy} / {rule} | {row.positions} / {row.events} | {row.sharpe:.3f} | {stress.sharpe:.3f} | {pct(row.average_net_lot_return)} | {pct(row.annualized_return,3)} | {pct(row.annualized_volatility,3)} | {pct(row.max_drawdown)} | {row.annualized_turnover:.2%} |")
    markdown += ["", "## Replacement decision", "",
        "Neither alternative passes the prewritten replacement gate: improve Sharpe at both costs on the same vendor policy; positive winner-minus-control mean; no worse drawdown; at least ten unique exposures across three owners; positive retained-lot mean after every company omission. The disruption-filtered discount rule is only one AMRX observation. The current candidate itself also lacks ten exposures and is not certified as a robust edge.", "",
        "## Inference and concentration", "",
        f"Winner HAC p={ref['inference']['p_value']:.3f}; winner-minus-page-absent controls p={comparison['p_value']:.3f}. Seven information-date clusters; descriptive bootstrap mean-lot 95% interval {pct(ref['lot_cluster_interval']['percentile_95_ci_mean_lot'][0])} to {pct(ref['lot_cluster_interval']['percentile_95_ci_mean_lot'][1])}. These intervals are conditional on the selected sample and are not selection-adjusted.", "",
        f"AMRX contributes {amrx_fraction:.1%} of net dollar P&L. Excluding it leaves mean net lot {pct(no_amrx.average_net_lot_return)} and Sharpe {no_amrx.sharpe:.3f}. Its omitted allocation remains cash. Mean pre-information descriptive CAR is {pct(ref['mean_pre_information_car'])}; this cannot be described as flat or as evidence that prediction P3 passed.", "",
        "Search disclosure: the preserved strict timing study has 42 strategy cells, 168 winner/control portfolio evaluations and 38 omission diagnostics; it records 111 earlier inference probes. A separate entry grid tested nine rules on another sample. This package compares two further entry/filter rules against the retained baseline, under two vendor policies and two cost assumptions (24 winner/control evaluations). Identical reruns corrected a serialization failure and verified the final audit; all attempts remain recorded. The known lower-bound multiplicity adjustment gives p=1 for all current winner tests. Counts are dependent and the older 111-probe inventory is not an exhaustive count of distinct strategies.", "",
        "## Factor, risk and capacity checks", "",
        f"Monthly US market/value/momentum regression uses 124 months, official Ken French factors and HAC(3). Coefficients: market {ref['factor_regression']['coefficients']['Mkt-RF']:.5f}, value {ref['factor_regression']['coefficients']['HML']:.5f}, momentum {ref['factor_regression']['coefficients']['Mom']:.5f}. Monthly cash-benchmark alpha {pct(ref['factor_regression']['coefficients']['const'],3)} (t={ref['factor_regression']['t_stats']['const']:.2f}). This negative alpha reflects, in part, zero-return idle cash versus the factor risk-free rate. Factor vintage is retrospective, never an entry signal.", "",
        f"Measured max marked gross {ref['risk_exposures']['max_gross_fraction']:.2%}, max name {ref['risk_exposures']['max_name_marked_fraction']:.2%}, max absolute net {ref['risk_exposures']['max_absolute_net_fraction']:.2%}; {ref['active_days']}/{ref['sessions']} active days; no drawdown de-risk trigger. Sparse exposure and idle cash limit tail/regime claims.", "",
        f"Dollar ADV uses 60 prior sessions and capacity=min(0.01*ADV/order_fraction) across both legs and entry/exit orders. Estimated limiting AUM is ${capacity_bound:,.0f} at 1% ADV, ${capacity_bound*5:,.0f} at 5%. $1m is an accounting normalization, not a claim of executable capacity; AMRX exit is about 2.19% ADV at that size. These are volume-based bounds, not profitable capacity estimates.", "",
        "Corwin-Schultz median full-spread estimates for AMRX are about 89bp, above the assumed 20bp round-trip stock fee. Even doubled stock costs are below this indicative spread. The fixed-cost results are a model benchmark pending execution-cost calibration. Webull adjustment/dividend and historical volume conventions are not independently certified; capacity is provisional. A zero spread estimate does not establish free execution.", "",
        "## Data and validation", "",
        "Frozen strict ledger: 18 all-market candidates across 15 events; 11 US candidates, with three MYL candidates excluded for unavailable predecessor prices. Eight scheduled reference lots remain. Every strict winner matches the frozen all-presentation audit. The Webull-only reference has four lots across three events; four TEVA reference lots use disclosed Yahoo prices. No prices were fetched by this evaluation; SPY supplies the US calendar and hedge.", "",
        "Every evaluation saves requests, filter/eligibility reasons, trades, lot cashflows, daily NAV, metrics, equity curve, capacity, factor coefficients and pre-information drift. Lot cashflows reconcile with NAV; the eight-lot reference reproduces the preserved figures exactly. 27 synthetic/guardrail tests pass. All price and input hashes are verified; primary files, hypothesis, config, original variants log and holdout lock are unchanged.", "",
        "## Holdout and next evidence", "",
        "There is no new blind out-of-sample result for this refined candidate. The 2024-2026 period has already been inspected. No formal final command was run, no lock reset, and no tuning of a claimed invisible test period. A genuinely unseen future event cohort and a calibrated spread/impact model are needed before upgrading this exploratory relation to a validated edge. Historical holdout comparisons, if later shown, must be labeled exposed-sample research.", "",
        "## Reproduce and edit", "", "Run `.venv/bin/python -m research.final_candidate.run` offline with the frozen licensed cache. Missing, short or altered files stop the run. Read `research/final_candidate/README.md` to create a new disclosed version; do not overwrite v1 or automatically replace the primary.", "",
        f"Detailed run: `{folder.relative_to(ROOT)}`. Sources: frozen FDA ledger/audit, cache manifest, and [official Ken French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)."]
    (OUT / "RESULTS.md").write_text("\n".join(markdown) + "\n")

    destination = ROOT / "output/pdf/backfill_working_candidate_v1.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    navy, teal = colors.HexColor("#142A42"), colors.HexColor("#137C82")
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=11, leading=14, spaceAfter=7, textColor=navy)
    title = ParagraphStyle("Title", parent=body, fontName="Helvetica-Bold", fontSize=19, leading=23, spaceAfter=12)
    heading = ParagraphStyle("Heading", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=7, spaceAfter=8)
    cell = ParagraphStyle("Cell", parent=body, fontSize=11, leading=13, spaceAfter=0)
    story = []
    def p(text):
        story.append(Paragraph(text, body))
    def h(text):
        story.append(Paragraph(text, heading))
    def table(rows, widths):
        values = [[Paragraph(escape(str(v)), cell) for v in row] for row in rows]
        t = Table(values, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0), colors.HexColor("#E4EEF3")),
            ("VALIGN", (0,0),(-1,-1), "TOP"), ("LINEBELOW", (0,0),(-1,0), .7, teal),
            ("LINEBELOW", (0,1),(-1,-1), .25, colors.HexColor("#D9E1E6")),
            ("LEFTPADDING", (0,0),(-1,-1), 6), ("RIGHTPADDING", (0,0),(-1,-1), 6),
            ("TOPPADDING", (0,0),(-1,-1), 5), ("BOTTOMPADDING", (0,0),(-1,-1), 5)]))
        story.extend([t, Spacer(1, 9)])
    story.append(Paragraph("Backfill | Working candidate v1", title))
    p("Frozen 4 October 2026. Post-result exploratory research. Retain the current candidate; neither fixed alternative passed the replacement gate. This does not replace or validate the registered primary.")
    h("Rule and execution")
    p("US listed owner; every FDA-listed presentation on the selected archived formulation page available, unallocated and nonempty. After both shortage and supplier evidence are available, identify the next US close. <b>Enter 20 additional sessions later; sell five sessions after entry.</b> No SMA filter. Supplier status is not reverified during the wait.")
    p("Equal 5% capital per event, split before exclusions; unused shares stay cash. Hedge each lot with SPY using 250 prior paired returns. Stock 10bp/SPY 2bp each side; hedge carry 50bp/year. Cash earns zero. Costs and carry doubled in stress.")
    h("Net in-sample evidence | June 2014-September 2024")
    rows = [["Metric", "Historical reference", "Webull-only"]]
    for label, key, formatter in [("Lots / events", None, None), ("Sharpe", "sharpe", lambda v:f"{v:.3f}"),
        ("Sharpe, doubled costs", None, None), ("Annualized return", "annualized_return", lambda v:pct(v,3)),
        ("Annualized volatility", "annualized_volatility", lambda v:f"{v:.3%}"),
        ("Max drawdown", "max_drawdown", pct), ("Annual turnover", "annualized_turnover", lambda v:f"{v:.2%}"),
        ("Mean net lot return", None, None)]:
        vals=[]
        for policy, m in [("reference_mix",ref), ("webull_only",web)]:
            if label=="Lots / events": v=f"{m['positions']} / {m['events']}"
            elif label=="Sharpe, doubled costs": v=f"{read(policy,cost=2)['sharpe']:.3f}"
            elif label=="Mean net lot return": v=pct(float(summary[(summary.vendor_policy==policy)&(summary.rule=='delay20_hold5')&(summary.cost_multiplier==1)].average_net_lot_return.iloc[0]))
            else: v=formatter(m[key])
            vals.append(v)
        rows.append([label,*vals])
    table(rows, [212,160,160])
    p("The reference contains four Yahoo-priced TEVA trades. Webull-only keeps those allocations in cash. Annual figures include inactive sessions and should not be read as typical returns on invested capital.")
    story.append(Image(str(folder / "reference_mix/delay20_hold5/costs1/winners/equity.png"), width=480, height=180, hAlign="LEFT"))
    story.append(PageBreak())

    story.append(Paragraph("Evidence and actual trades", title))
    p("The frozen strict ledger has 18 all-market candidates across 15 events. The US subset has 11 candidates; three MYL candidates are excluded because predecessor prices are unavailable. Eight reference lots remain across seven events and five owners. No successor history substitutes for a delisted predecessor.")
    h("Actual reference fills and net lot returns")
    rows=[["Owner", "Event", "Buy close", "Sell close", "Net lot"]]
    for row in lots.itertuples():
        rows.append([row.ticker,row.event_id,str(row.trade_date)[:10],str(row.exit_date)[:10],pct(row.net_lot_return)])
    table(rows,[65,54,142,142,129])
    p("Lot returns reconcile stock and hedge cashflows, both-side transaction costs and hedge carry. They measure return on allocated lot capital; the portfolio metrics also account for cash and overlapping lots.")
    h("What the evidence does and does not show")
    p("Supplier status comes from one point-in-time FDA formulation page within the 30-day rule. All parent-owned presentation rows on that page qualify. This does not establish that the manufacturer's whole catalogue is available, that it has spare capacity, or that another owner's strength/route is commercially substitutable.")
    p("A disrupted counterpart requires a separately listed owner on the exact same formulation capture. Different archive timestamps and the same owner are rejected. Page-absent generic-maker controls use the same event dates; absence does not prove they do not manufacture the product.")
    p("Some shortage observation dates remain uncertain. Entry uses evidence availability rather than a guessed earlier onset. Archived status can be stale at the delayed entry; the frozen rule does not manufacture an update.")
    story.append(PageBreak())

    story.append(Paragraph("Bounded improvement check", title))
    p("Two alternatives were fixed before this run: immediate entry when the preceding close is below its trailing 60-session average; and the same rule requiring a documented disrupted listed counterpart. Both hold five sessions and keep the same frozen event allocations.")
    rows=[["Policy / entry rule", "Lots", "Sharpe", "x2 costs", "Mean net lot"]]
    for policy in ("reference_mix","webull_only"):
        for rule,label in [("delay20_hold5","Wait 20"),("below_sma60_hold5","SMA60 immediate"),("below_sma60_disrupted_hold5","SMA60 + disruption")]:
            row=summary[(summary.vendor_policy==policy)&(summary.rule==rule)&(summary.cost_multiplier==1)].iloc[0]
            stress=summary[(summary.vendor_policy==policy)&(summary.rule==rule)&(summary.cost_multiplier==2)].iloc[0]
            rows.append([("Reference" if policy=="reference_mix" else "Webull")+" / "+label,row.positions,f"{row.sharpe:.3f}",f"{stress.sharpe:.3f}",pct(row.average_net_lot_return)])
    table(rows,[236,44,72,76,104])
    p("Neither alternative passes. The disruption condition leaves only AMRX. Replacement required higher Sharpe at both costs on the same vendor policy, positive winner-minus-control mean, no worse drawdown, ten unique exposures across three owners, and positive retained-lot means after every company omission. The current candidate also lacks ten exposures; keeping it is a working decision, not certification.")
    h("Already-tested nearby timing | reference Sharpe")
    rows=[["Extra entry sessions", "Hold 1", "Hold 5", "Hold 20"]]
    for delay in [0,5,20]:
        rows.append([delay,*[f"{near[(near.entry_delay_sessions==delay)&(near.hold_days==hold)].sharpe.iloc[0]:.3f}" for hold in [1,5,20]]])
    table(rows,[235,99,99,99])
    p(f"AMRX contributes {amrx_fraction:.1%} of net dollar profit. Without it, mean net lot return is {pct(no_amrx.average_net_lot_return)} and Sharpe {no_amrx.sharpe:.3f}. Excluding entry-year 2023 leaves Sharpe 0.205. Omitted allocations stay cash. The relation is weak without its main contributor.")
    story.append(PageBreak())

    story.append(Paragraph("Inference, factors and drawdowns", title))
    h("Uncertainty and research history")
    ci=ref['lot_cluster_interval']['percentile_95_ci_mean_lot']
    p(f"Calendar-time winner HAC(60) t={ref['inference']['hac_t']:.2f}, p={ref['inference']['p_value']:.3f}. Winner-minus-control p={comparison['p_value']:.3f}. Mean-lot descriptive bootstrap interval: {pct(ci[0])} to {pct(ci[1])}, resampling seven information-date clusters together. These selected-sample intervals are not confirmatory or adjusted for choosing the timing.")
    p("Preserved strict timing research contains 42 strategy cells, 168 winner/control evaluations and 38 omission diagnostics. Its log records 111 earlier inference probes. A separate sample tested nine entry/hold rules. This package adds two entry/filter alternatives, two vendor policies and two costs: 24 winner/control evaluations. Identical reruns corrected a serialization failure and verified the final audit; all attempts remain recorded. Known lower-bound multiplicity-adjusted winner p-values are all 1.")
    p(f"Mean descriptive CAR over 20 sessions strictly before all evidence was available is {pct(ref['mean_pre_information_car'])}. Beta is fitted using only pre-information prices. This is not flat and does not establish that the pre-drift prediction passed. The existing pre-entry diagnostic is retained separately because a delayed entry's lookback can include post-announcement days.")
    h("US monthly factor check | 124 months, HAC(3)")
    rows=[["Factor / intercept", "Coefficient", "t-stat"]]
    for k,label in [("Mkt-RF","Market"),("HML","Value"),("Mom","Momentum"),("const","Monthly alpha")]:
        rows.append([label,f"{ref['factor_regression']['coefficients'][k]:.5f}",f"{ref['factor_regression']['t_stats'][k]:.2f}"])
    table(rows,[290,121,121])
    p("Official Ken French current factor vintage; retrospective exposure check, never a trading input. Regression subtracts its risk-free rate. Negative alpha partly reflects zero-return idle cash versus that benchmark; positive Sharpe above zero is not evidence of positive cash-benchmark alpha.")
    p(f"Only {ref['active_days']} of {ref['sessions']} sessions have positions. Worst month {pct(ref['worst_month'])}; max drawdown {pct(ref['max_drawdown'])}. No 10% de-risk trigger. Active-year portfolio returns: 2014 -0.141%, 2016 +0.047%, 2021 +0.302%, 2023 +0.885%. Sparse exposure prevents persuasive regime or tail-risk claims.")
    p(f"The previously evaluated US primary remains negative: {primary['positions']} lots / {primary['events']} events, Sharpe {primary['sharpe']:.3f}, annual return {pct(primary['annualized_return'])}, max drawdown {pct(primary['max_drawdown'])}, HAC p={primary['inference']['p_value']:.3f}. Refinement followed that result; it does not confirm the original hypothesis.")
    story.append(PageBreak())

    story.append(Paragraph("Risk, capacity and reproducibility", title))
    p("Caps: 8% name, 30% listing market, 50% healthcare, 150% gross, 25% absolute net. Independent lots retain their expiry. A 10% drawdown halves exposure at the next session; restore after 20 sessions. No early shortage-resolution exit. All stocks in this candidate are US listings, valued in USD.")
    p(f"Observed max marked name {ref['risk_exposures']['max_name_marked_fraction']:.2%}, gross {ref['risk_exposures']['max_gross_fraction']:.2%}, absolute net {ref['risk_exposures']['max_absolute_net_fraction']:.2%}. Price drift can move marked exposure above an entry-sized cap; none here breaches its cap.")
    h("Liquidity and modeled execution")
    p(f"ADV is average dollar volume over 60 preceding sessions. For each date and symbol, sum absolute lot orders across both legs. Capacity AUM = participation limit x ADV / order fraction of NAV. The minimum across entries and exits is <b>${capacity_bound:,.0f} at 1% ADV</b>, or ${capacity_bound*5:,.0f} at 5%. AMRX exit is limiting. $1m is an accounting normalization; its AMRX exit is about 2.19% ADV.")
    p("Corwin-Schultz two-day ranges give AMRX full-spread estimates near 89bp. The frozen 10bp-per-side stock model, even doubled, is below this indicative spread. Treat reported performance as a fixed-cost benchmark pending calibration. These volume bounds are not profitable capacity estimates. Webull adjustment/dividend and volume conventions are not independently certified; zero estimated spread does not establish free execution.")
    h("Audit and reproduction")
    p("Frozen ledgers, all-presentation audits, price/factor manifests, source/code hashes and dedicated lifecycle logs are included. Save requests, rejected entries, eligibility, trades, lot cashflows, daily equity, metrics, factors, pre-information drift and capacity. The reference reproduces exactly and every completed lot ledger reconciles with NAV. All 27 synthetic/guardrail tests pass. No new stock prices or holdout evaluation were used.")
    p("Run <font name='Courier'>.venv/bin/python -m research.final_candidate.run</font> with the local frozen cache. Missing or altered files stop execution. Raw vendor prices remain gitignored; reproducing numerical results requires that licensed cache. Make a new disclosed version to edit rules; keep v1 and all prior results.")
    h("What remains unconfirmed")
    p("The 2024-2026 period has already been inspected; this candidate has no new blind OOS result. No final command or lock reset occurred. A genuinely unseen cohort and calibrated costs are needed before calling this a validated edge. This is a five-page research note, not a complete competition submission with a certified unseen test.")
    p("Sources: frozen FDA evidence and quote manifest; official Ken French Data Library (mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html). Detailed CSVs and hashes accompany the report in results/research/final_candidate_v1_20261004.")

    def footer(canvas, doc):
        canvas.setStrokeColor(teal); canvas.line(40,35,572,35)
        canvas.setFont("Helvetica",11); canvas.setFillColor(navy)
        canvas.drawString(40,19,"Backfill v1 | exploratory | 4 October 2026")
        canvas.drawRightString(572,19,str(doc.page))
    SimpleDocTemplate(str(destination), pagesize=(612,792), rightMargin=40,leftMargin=40,
        topMargin=38,bottomMargin=48,title="Backfill working candidate v1",author="Gator Hacks team").build(story,onFirstPage=footer,onLaterPages=footer)
    print(destination)
    print(OUT / "RESULTS.md")


if __name__ == "__main__":
    main()
