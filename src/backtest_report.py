"""Build one HTML report from completed backtest bundles (reads results only; never evaluates).

    uv run python src/backtest_report.py results/backfill/<id> [results/backfill/<id> ...]

Each argument is a bundle written by run_all.py --variant <name>. The committed final-candidate
results are added as reference rows. Output: results/backtest_report/index.html.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "results/research/final_candidate_v1_20261004"
OUT = ROOT / "results/backtest_report/index.html"
PROOF = ROOT / "proof/freeze-v1"

DESCRIPTIONS = {
    "primary": "Registered primary: available US suppliers, hold 60, SPY beta hedge",
    "capture60": "Supplier capture window 60 days",
    "allocation": "Include suppliers on allocation",
    "certain_dates": "Exclude uncertain shortage dates",
    "all_flags": "Include rename/spike flagged events",
    "hold20": "Hold 20 sessions",
    "hold40": "Hold 40 sessions",
    "hold120": "Hold 120 sessions",
    "all_markets": "Add non-US listed winners (local index hedge)",
}


def lot_returns(path):
    """Per-lot net P&L from cash flows (both legs, costs included, hedge carry excluded)."""
    trades = pd.read_csv(path)
    rows = []
    for lot, g in trades.groupby("lot_id", sort=False):
        entry = g[(g.leg == "stock") & (g.reason == "entry")]
        exit_ = g[g.reason == "expiry"]
        basis = entry.usd_notional.sum()
        pnl = -g.usd_notional.sum() - g.cost.sum()
        rows.append(dict(lot=lot, ticker=entry.ticker.iloc[0], event=int(entry.event_id.iloc[0]),
                         entry=entry.date.iloc[0], exit=exit_.date.iloc[0] if len(exit_) else "open",
                         basis=round(basis, 2), pnl=round(pnl, 2), ret=pnl / basis if basis else 0.0))
    return rows


def summarize(folder):
    metrics = json.loads((folder / "metrics.json").read_text())
    equity = pd.read_csv(folder / "equity.csv")
    lots = lot_returns(folder / "trades.csv")
    nav = equity.nav
    wins = sum(r["pnl"] > 0 for r in lots)
    return dict(
        metrics=metrics, lots=lots,
        total_return=nav.iloc[-1] / nav.iloc[0] - 1, net_pnl=nav.iloc[-1] - nav.iloc[0],
        wins=wins, losses=len(lots) - wins, win_rate=wins / len(lots) if lots else None,
        trades_pnl=sum(r["pnl"] for r in lots),
        avg_lot=sum(r["ret"] for r in lots) / len(lots) if lots else None,
        period=f"{equity.date.iloc[0]} to {equity.date.iloc[-1]}",
        equity=[[d, round(v / nav.iloc[0] * 100, 4)] for d, v in zip(equity.date, nav)],
    )


def bundle_rows(bundle):
    rows = []
    for variant_dir in sorted(p for p in bundle.iterdir() if p.is_dir()):
        variant = variant_dir.name
        winner = summarize(variant_dir / "winner/costs1")
        doubled = json.loads((variant_dir / "winner/costs2/metrics.json").read_text())
        placebo = json.loads((variant_dir / "placebo/costs1/metrics.json").read_text())
        paired = json.loads((variant_dir / "comparison_costs1.json").read_text())
        rows.append(dict(source="rerun", name=variant, bundle=bundle.name,
                         description=DESCRIPTIONS.get(variant, variant), **winner,
                         sharpe_x2=doubled["sharpe"], placebo_sharpe=placebo["sharpe"],
                         paired_p=paired["p_value"]))
    return rows


def final_candidate_rows():
    """Committed (not rerun) frozen candidate results; its licensed cache is not available locally."""
    latest = json.loads((FINAL / "latest.json").read_text())
    run = ROOT / latest["directory"]
    summary = pd.read_csv(run / "summary.csv")
    rows = []
    for policy in ("reference_mix", "webull_only"):
        folder = run / policy / "delay20_hold5/costs1/winners"
        if not folder.exists():
            continue
        s = summarize(folder)
        x2 = summary[(summary.vendor_policy == policy) & (summary.rule == "delay20_hold5")
                     & (summary.cost_multiplier == 2)].iloc[0]
        x1 = summary[(summary.vendor_policy == policy) & (summary.rule == "delay20_hold5")
                     & (summary.cost_multiplier == 1)].iloc[0]
        rows.append(dict(source="committed", name=f"final_candidate/{policy}", bundle=run.name,
                         description=f"Frozen working candidate v1 (wait 20, hold 5), {policy.replace('_', ' ')}",
                         **s, sharpe_x2=x2.sharpe, placebo_sharpe=None, paired_p=x1.paired_p))
    return rows


def pct(x, digits=2):
    return "–" if x is None or pd.isna(x) else f"{x * 100:+.{digits}f}%"


def num(x, digits=2):
    return "–" if x is None or pd.isna(x) else f"{x:+.{digits}f}"


def cls(x):
    return "" if x is None or pd.isna(x) or x == 0 else ("pos" if x > 0 else "neg")


def proof_section():
    """Freeze proof card from proof/freeze-v1 (receipt written by proof.anchor_solana)."""
    if not (PROOF / "receipt.json").exists():
        return ('<p class="notes">Not yet anchored. Run <code>proof.make_manifest</code> then '
                '<code>proof.anchor_solana</code> after tagging <code>freeze-v1</code>.</p>')
    r = json.loads((PROOF / "receipt.json").read_text())
    files = len(json.loads((PROOF / "manifest.json").read_text())["files"])
    rows = [("Tag / commit", f"<code>{r['tag']}</code> · <code>{r['commit'][:12]}</code>"),
            ("Frozen files", str(files)),
            ("Manifest hash", f"<code>{r['manifest_sha256']}</code>"),
            ("On-chain memo", f"<code>{r['memo']}</code>"),
            ("Transaction", f"<a href='{r['explorer']}' target='_blank' rel='noopener'>{r['signature'][:24]}…</a> (Solana devnet)"),
            ("Block time / slot", f"{r['block_time']} · {r['slot']}"),
            ("Verify", "<code>uv run python -m proof.verify_proof</code>")]
    return "<table class='proof'>" + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows) + "</table>"


def render(rows):
    primary = next(r for r in rows if r["name"] == "primary")
    m = primary["metrics"]
    kpis = [
        ("Net P&L", f"{primary['net_pnl']:,.2f} ({primary['total_return'] * 100:+.2f}%)", primary["net_pnl"]),
        ("Annualized Return", pct(m["annualized_return"]), m["annualized_return"]),
        ("Annualized Volatility", f"{m['annualized_volatility'] * 100:.2f}%", None),
        ("Sharpe (ann.)", f"{m['sharpe']:.3f}", m["sharpe"]),
        ("Sharpe, costs ×2", f"{primary['sharpe_x2']:.3f}", primary["sharpe_x2"]),
        ("Max Drawdown", f"{abs(m['max_drawdown']) * 100:.2f}%", -1),
        ("Win Rate", f"{primary['win_rate'] * 100:.1f}% ({primary['wins']}/{len(primary['lots'])})", None),
        ("Trades", f"{len(primary['lots'])} (W{primary['wins']}/L{primary['losses']}) · {m['events']} events", None),
        ("Trades Net P&L", f"{primary['trades_pnl']:,.2f}", primary["trades_pnl"]),
        ("Costs (txn + carry)", f"{m['transaction_cost'] + m['hedge_carry_cost']:,.2f}", None),
        ("Winner HAC p-value", f"{m['inference']['p_value']:.3f}", None),
        ("Winner − placebo p", f"{primary['paired_p']:.3f}", None),
    ]
    kpi_html = "".join(f'<div class="kpi-card"><div class="kpi-label">{k}</div>'
                       f'<div class="kpi-value {cls(s)}">{v}</div></div>' for k, v, s in kpis)

    table = []
    for r in rows:
        mm = r["metrics"]
        tag = '<span class="tag">committed</span>' if r["source"] == "committed" else ""
        table.append(
            f"<tr><td><b>{r['name']}</b> {tag}<div class='muted'>{r['description']}</div></td>"
            f"<td>{mm['events']}</td><td>{len(r['lots'])}</td>"
            f"<td class='{cls(r['total_return'])}'>{pct(r['total_return'])}</td>"
            f"<td class='{cls(mm['annualized_return'])}'>{pct(mm['annualized_return'], 3)}</td>"
            f"<td>{mm['annualized_volatility'] * 100:.2f}%</td>"
            f"<td class='{cls(mm['sharpe'])}'><b>{mm['sharpe']:+.2f}</b></td>"
            f"<td class='{cls(r['sharpe_x2'])}'>{num(r['sharpe_x2'])}</td>"
            f"<td class='neg'>{mm['max_drawdown'] * 100:.2f}%</td>"
            f"<td>{'–' if r['win_rate'] is None else f'{r['win_rate'] * 100:.0f}%'}</td>"
            f"<td class='{cls(r['avg_lot'])}'>{pct(r['avg_lot'])}</td>"
            f"<td>{num(r['placebo_sharpe'])}</td>"
            f"<td>{mm['inference']['p_value']:.3f}</td>"
            f"<td>{'–' if r['paired_p'] is None else f'{r['paired_p']:.3f}'}</td></tr>")

    years = sorted({y for r in rows for y in r["metrics"]["returns_by_year"]})
    yearly = []
    for r in rows:
        cells = []
        for y in years:
            v = r["metrics"]["returns_by_year"].get(y)
            shade = "" if not v else f"background:rgba({'38,166,154' if v > 0 else '239,83,80'},{min(abs(v) / .03, 1) * .55 + .08:.2f})"
            cells.append(f"<td style='{shade}'>{'' if v is None else ('·' if v == 0 else f'{v * 100:+.2f}%')}</td>")
        yearly.append(f"<tr><td><b>{r['name']}</b></td>{''.join(cells)}</tr>")

    trades = "".join(
        f"<tr><td>{t['entry']}</td><td>{t['exit']}</td><td><b>{t['ticker']}</b></td><td>{t['event']}</td>"
        f"<td>{t['basis']:,.0f}</td><td class='{cls(t['pnl'])}'>{t['pnl']:,.2f}</td>"
        f"<td class='{cls(t['ret'])}'>{pct(t['ret'])}</td></tr>" for t in primary["lots"])

    series = [dict(name=r["name"], data=r["equity"], primary=r["name"] == "primary") for r in rows]
    bundles = ", ".join(sorted({r["bundle"] for r in rows if r["source"] == "rerun"}))
    template = (ROOT / "src/backtest_report_template.html").read_text()
    return (template.replace("{{KPIS}}", kpi_html).replace("{{TABLE}}", "".join(table))
            .replace("{{YEAR_HEAD}}", "".join(f"<th>{y}</th>" for y in years))
            .replace("{{YEARLY}}", "".join(yearly)).replace("{{TRADES}}", trades)
            .replace("{{PERIOD}}", primary["period"]).replace("{{BUNDLES}}", bundles)
            .replace("{{N}}", str(sum(r["source"] == "rerun" for r in rows)))
            .replace("{{PROOF}}", proof_section()).replace("{{SERIES}}", json.dumps(series)))


def main(paths):
    rows = [row for p in paths for row in bundle_rows(Path(p))]
    order = list(DESCRIPTIONS)
    rows.sort(key=lambda r: order.index(r["name"]) if r["name"] in order else len(order))
    rows += final_candidate_rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(rows))
    pd.DataFrame([dict(variant=r["name"], source=r["source"], bundle=r["bundle"], events=r["metrics"]["events"],
                       positions=len(r["lots"]), total_return=r["total_return"],
                       annualized_return=r["metrics"]["annualized_return"],
                       annualized_volatility=r["metrics"]["annualized_volatility"], sharpe=r["metrics"]["sharpe"],
                       sharpe_costs_x2=r["sharpe_x2"], max_drawdown=r["metrics"]["max_drawdown"],
                       win_rate=r["win_rate"], avg_lot_return=r["avg_lot"], placebo_sharpe=r["placebo_sharpe"],
                       winner_p=r["metrics"]["inference"]["p_value"], winner_minus_placebo_p=r["paired_p"])
                  for r in rows]).to_csv(OUT.with_name("summary.csv"), index=False)
    print(f"Wrote {OUT} and {OUT.with_name('summary.csv')}")


if __name__ == "__main__":
    main(sys.argv[1:])
