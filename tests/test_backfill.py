"""Hand-computed fixtures only. No vendor calls, real prices, or holdout results."""
import json
import tempfile
import unittest
import subprocess
import importlib.util
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

import config
from backfill.analysis import capacity, metrics, write_report
from backfill.engine import run_portfolio, schedule_lots
from backfill.events import build_candidates, map_company
from backfill.guardrails import require_oos_freeze, reserve_holdout
from backfill.prices import COLUMNS, load_cache, normalize_yahoo, sha256, symbol_path
from backfill.settings import Settings
from strategies.backfill import select


def bars(days, closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(dict(open=closes, high=closes * 1.01, low=closes * .99,
                             close=closes, adj_close=closes, volume=1_000_000,
                             dividends=0.0, splits=0.0), index=pd.DatetimeIndex(days, name="date"))


def fixture():
    days = pd.bdate_range("2020-01-01", periods=12)
    hedge = np.array([100, 110, 99, 90, 99, 99, 99, 99, 99, 99, 99, 99], dtype=float)
    stock = np.array([100, 110, 99, 90, 99, 108.9] + [119.79] * 6)
    prices = {"TEST": bars(days, stock), "SPY": bars(days, hedge), "^GSPC": bars(days, hedge)}
    settings = replace(Settings(), start=str(days[3].date()), end=str(days[9].date()),
                       hold_days=2, beta_lookback=2, event_weight=.10,
                       name_cap=1, country_cap=1, sector_cap=1, gross_cap=10, net_cap=10,
                       foreign_long_cap=1, initial_nav=1_000, hedge_carry_bps_year=0,
                       costs_bps={"US": 0}, hedge_cost_bps=0, adv_lookback=2)
    events = pd.DataFrame([dict(event_id=1, ticker="TEST", country="US", benchmark="SPY", role="winner",
                                trade_ready_date=days[3], winner_count=1)])
    return days, prices, settings, events


class AccountingTests(unittest.TestCase):
    def test_one_lot_next_close_and_two_intervals(self):
        days, prices, settings, events = fixture()
        result = run_portfolio(select(events, settings=settings), prices, settings)
        # Enter at day 4's close (99), earn two +10% intervals, exit day 6.
        self.assertEqual(result.lots.trade_date.iloc[0], days[4])
        self.assertEqual(result.lots.exit_date.iloc[0], days[6])
        self.assertAlmostEqual(result.lots.beta.iloc[0], 1)
        self.assertAlmostEqual(result.equity.loc[days[4], "nav"], 1_000)
        self.assertAlmostEqual(result.equity.loc[days[6], "nav"], 1_021)
        self.assertEqual(result.equity.active_lots.iloc[-1], 0)
        self.assertEqual(len(result.trades), 4)

    def test_costs_both_legs_and_no_same_bar_gain(self):
        days, prices, settings, events = fixture()
        settings = replace(settings, costs_bps={"US": 10}, hedge_cost_bps=2)
        result = run_portfolio(select(events, settings=settings), prices, settings)
        # Entry stock 100*.001=.10; hedge 100*.0002=.02.
        # Exit stock 121*.001=.121; hedge 100*.0002=.02.
        self.assertAlmostEqual(result.equity.loc[days[4], "nav"], 999.88)
        self.assertAlmostEqual(result.trades.cost.sum(), .261)
        self.assertAlmostEqual(result.equity.nav.iloc[-1], 1020.739)

    def test_overlap_keeps_original_expiries(self):
        days, prices, settings, events = fixture()
        second = events.iloc[0].to_dict()
        second.update(event_id=2, trade_ready_date=days[4])
        events = pd.concat([events, pd.DataFrame([second])], ignore_index=True)
        result = run_portfolio(select(events, settings=settings), prices, settings)
        self.assertEqual(result.lots.exit_date.tolist(), [days[6], days[7]])
        self.assertEqual(result.equity.loc[days[5], "active_lots"], 2)
        self.assertEqual(result.equity.loc[days[6], "active_lots"], 1)

    def test_cap_binding_leaves_cash(self):
        _, prices, settings, events = fixture()
        second = events.iloc[0].to_dict()
        second["event_id"] = 2
        events = pd.concat([events, pd.DataFrame([second])], ignore_index=True)
        settings = replace(settings, name_cap=.08)
        result = run_portfolio(select(events, settings=settings), prices, settings)
        # Two simultaneous 10% requests share 8% name headroom equally.
        self.assertEqual(result.lots.entry_usd.tolist(), [40, 40])
        self.assertAlmostEqual(result.equity.nav.iloc[-1], 1016.8)

    def test_missing_bar_fails_instead_of_shortening_hold(self):
        days, prices, settings, events = fixture()
        prices["TEST"] = prices["TEST"].drop(days[5])
        with self.assertRaisesRegex(ValueError, "missing bar during required hold"):
            run_portfolio(select(events, settings=settings), prices, settings)

    def test_boundary_excludes_lot_without_using_stock_end(self):
        days, prices, settings, events = fixture()
        settings = replace(settings, end=str(days[5].date()))
        lots, audit = schedule_lots(select(events, settings=settings), prices, settings)
        self.assertEqual(lots, [])
        self.assertEqual(audit.reason.tolist(), ["hold_crosses_end_boundary"])

    def test_report_smoke_on_synthetic_data(self):
        _, prices, settings, events = fixture()
        result = run_portfolio(select(events, settings=settings), prices, settings)
        with tempfile.TemporaryDirectory() as tmp:
            report = write_report(result, prices, tmp, settings)
            self.assertAlmostEqual(report["transaction_cost"], 0)
            self.assertTrue((Path(tmp) / "equity.png").exists())
            self.assertTrue((Path(tmp) / "capacity.csv").exists())
            self.assertGreater(metrics(result, settings)["annualized_turnover"], 0)
            self.assertFalse(capacity(result, prices, settings).empty)

    def test_foreign_marks_include_fx_on_both_legs(self):
        days, original, settings, events = fixture()
        prices = {"TEST.L": original["TEST"], "ISF.L": original["SPY"], "^FTSE": original["^GSPC"]}
        rates = np.ones(len(days))
        rates[5:7] = [1.1, 1.2]
        prices["GBPUSD=X"] = bars(days, rates)
        events["ticker"], events["country"], events["benchmark"] = "TEST.L", "UK", "ISF.L"
        settings = replace(settings, costs_bps={"UK": 0})
        result = run_portfolio(select(events, settings=settings), prices, settings)
        # Local net gain is GBP21; both legs settle at USD1.20 per pound.
        self.assertAlmostEqual(result.equity.nav.iloc[-1], 1025.2)

    def test_drawdown_reduces_next_session_without_resetting_expiry(self):
        days, prices, settings, events = fixture()
        prices["TEST"].loc[days[5]:, ["adj_close", "close"]] = 49.5
        settings = replace(settings, event_weight=.9, hold_days=6, end=str(days[11].date()), recovery_sessions=2)
        result = run_portfolio(select(events, settings=settings), prices, settings)
        reductions = result.trades[result.trades.reason == "de_risk"]
        self.assertEqual(reductions.date.iloc[0], days[6])
        self.assertEqual(result.lots.exit_date.iloc[0], days[10])
        self.assertAlmostEqual(result.equity.nav.iloc[-1], 550)


class EvidenceTests(unittest.TestCase):
    def setup_evidence(self):
        events = pd.DataFrame([dict(event_id=1, product="Test injection", ai_key="test injection",
                                    public_date="2020-01-02", left_censored=False, rename_window=False,
                                    spike_week=False, rename_suspect=False, date_uncertain=False)])
        suppliers = pd.DataFrame([
            dict(capture_date="2020-01-02", capture_ts="20200102120000", ai_key="test injection",
                 company="Maker A", presentation="10mg injection", availability="available",
                 availability_raw="On allocation", on_allocation=True, page_status="Currently in Shortage"),
            dict(capture_date="2020-01-05", capture_ts="20200105120000", ai_key="test injection",
                 company="Maker A", presentation="10mg injection", availability="available",
                 availability_raw="Available", on_allocation=False, page_status="Currently in Shortage")])
        mapping = pd.DataFrame([dict(company_pattern="Maker A", ticker="A", country="US", listed_from="2014-01-01",
                                     listed_to="", is_generic_maker=1),
                                dict(company_pattern="Maker B", ticker="B", country="US", listed_from="2014-01-01",
                                     listed_to="", is_generic_maker=1)])
        return events, suppliers, mapping

    def test_capture_not_selected_for_favorable_availability(self):
        events, suppliers, mapping = self.setup_evidence()
        ledger, audit = build_candidates(events, suppliers, mapping)
        self.assertFalse((ledger.role == "winner").any())
        self.assertIn("no_listed_available_winner", audit.reason.tolist())
        self.assertEqual(ledger.capture_ts.iloc[0], "20200102120000")
        allocation, _ = build_candidates(events, suppliers, mapping, include_allocation=True)
        self.assertEqual(allocation[allocation.role == "winner"].ticker.tolist(), ["A"])
        self.assertEqual(allocation[allocation.role == "placebo"].ticker.tolist(), ["B"])
        self.assertIn("unverified", allocation[allocation.role == "placebo"].control_definition.iloc[0])

    def test_future_revision_quarantines_page(self):
        events, suppliers, mapping = self.setup_evidence()
        suppliers["company_update_date"] = "2021-01-01"
        ledger, audit = build_candidates(events, suppliers, mapping)
        self.assertTrue(ledger.empty)
        self.assertIn("future_revision_in_capture", audit.reason.tolist())

    def test_dated_owner_transitions(self):
        mapping = pd.read_csv(Path(__file__).resolve().parents[1] / "data/company_ticker_map.csv",
                              keep_default_na=False)
        self.assertEqual(map_company("Hospira", mapping, "2015-02-07").ticker, "HSP")
        self.assertEqual(map_company("Hospira", mapping, "2015-09-03").ticker, "PFE")
        self.assertEqual(map_company("Mylan", mapping, "2019-01-01").ticker, "MYL")
        self.assertEqual(map_company("Mylan", mapping, "2021-01-01").ticker, "VTRS")
        self.assertEqual(map_company("Sandoz", mapping, "2020-01-01").ticker, "NOVN.SW")
        self.assertEqual(map_company("Sandoz", mapping, "2024-01-01").ticker, "SDZ.SW")

    def test_future_names_do_not_change_rename_flag(self):
        path = Path(__file__).resolve().parents[1] / "src/03_parse_main.py"
        spec = importlib.util.spec_from_file_location("test_parse_main", path)
        parser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parser)
        event = pd.DataFrame([dict(event_id=1, coarse_key="alpha", public_date=pd.Timestamp("2020-06-01"),
                                  left_censored=False)])
        status = pd.DataFrame([dict(coarse_key="alpha beta", ai_key="alpha beta injection", status="Current",
                                   snapshot_date=pd.Timestamp("2020-01-01")),
                               dict(coarse_key="alpha", ai_key="alpha injection", status="Current",
                                   snapshot_date=pd.Timestamp("2020-06-01"))])
        future = pd.DataFrame([dict(coarse_key="alpha", ai_key="alpha and delta injection", status="Current",
                                   snapshot_date=pd.Timestamp("2021-01-01"))])
        self.assertEqual(parser.rename_suspects(event, status), {1: "alpha beta"})
        self.assertEqual(parser.rename_suspects(event, pd.concat([status, future])), {1: "alpha beta"})


class GuardTests(unittest.TestCase):
    def test_final_requires_tag_at_head_and_clean_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for args in [["init", "-q"], ["config", "user.email", "fixture@example.test"],
                         ["config", "user.name", "Synthetic Fixture"], ["commit", "--allow-empty", "-qm", "Fixture"],
                         ["tag", "freeze-oos"]]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            self.assertTrue(require_oos_freeze(root))
            (root / "unreviewed.txt").write_text("Fixture dirty state\n")
            with self.assertRaisesRegex(ValueError, "clean working tree"):
                require_oos_freeze(root)

    def test_oos_settings_and_attempt_lock(self):
        with self.assertRaisesRegex(ValueError, "Holdout locked"):
            replace(Settings(), end=config.OOS_START)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attempt.json"
            reserve_holdout(path, {"test": True})
            with self.assertRaisesRegex(ValueError, "already attempted"):
                reserve_holdout(path, {"test": True})

    def test_cache_hash_and_missing_symbol_fail_closed(self):
        days, prices, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = symbol_path(tmp, "TEST")
            prices["TEST"].reset_index().to_csv(path, index=False)
            manifest = dict(requested_end_exclusive="2020-02-01", symbols={"TEST": {
                "file": path.name, "sha256": sha256(path)}}, exclusions={}, failures=[])
            (Path(tmp) / "manifest.json").write_text(json.dumps(manifest))
            loaded, _ = load_cache(tmp, ["TEST"], evaluation_end="2020-01-31")
            self.assertEqual(len(loaded["TEST"]), len(days))
            with self.assertRaisesRegex(ValueError, "cache miss"):
                load_cache(tmp, ["ABSENT"], evaluation_end="2020-01-31")
            path.write_text(path.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "changed cache"):
                load_cache(tmp, ["TEST"], evaluation_end="2020-01-31")

    def test_lse_currency_units_and_actions_preserved(self):
        frame = pd.DataFrame({"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0],
                              "Adj Close": [98.0], "Volume": [500], "Dividends": [2.0], "Stock Splits": [0.0]},
                             index=pd.DatetimeIndex(["2020-01-02"], tz="Europe/London"))
        normalized = normalize_yahoo(frame, "TEST.L")
        self.assertAlmostEqual(normalized.close.iloc[0], 1.0)
        self.assertAlmostEqual(normalized.adj_close.iloc[0], .98)
        self.assertAlmostEqual(normalized.dividends.iloc[0], .02)
        self.assertEqual(normalized.volume.iloc[0], 500)

    def test_full_offline_bundle_with_synthetic_inputs(self):
        from backfill import pipeline

        days, prices, settings, _ = fixture()
        prices["CONTROL"] = prices["TEST"].copy()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for args in [["init", "-q"], ["config", "user.email", "fixture@example.test"],
                         ["config", "user.name", "Synthetic Fixture"], ["commit", "--allow-empty", "-qm", "Fixture"]]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            (root / "HYPOTHESIS.md").write_text("Synthetic fixture only\n")
            sources = root / "inputs"
            sources.mkdir()
            public = str(days[3].date())
            pd.DataFrame([dict(event_id=1, product="test injection", ai_key="test injection", coarse_key="test", public_date=public)]).to_csv(
                sources / "events.csv", index=False)
            pd.DataFrame([dict(snapshot_date=public, coarse_key="test", ai_key="test injection", status="Current")]).to_csv(
                sources / "status.csv", index=False)
            pd.DataFrame([dict(capture_date=public, capture_ts=days[3].strftime("%Y%m%d") + "120000",
                               ai_key="test injection", company="Test maker", presentation="10mg injection",
                               availability="available", availability_raw="Available", on_allocation=False,
                               page_status="Currently in Shortage")]).to_csv(sources / "suppliers.csv", index=False)
            pd.DataFrame([dict(company_pattern="Test maker", ticker="TEST", country="US", listed_from="2014-01-01",
                               listed_to="", is_generic_maker=1),
                          dict(company_pattern="Control maker", ticker="CONTROL", country="US", listed_from="2014-01-01",
                               listed_to="", is_generic_maker=1)]).to_csv(sources / "map.csv", index=False)
            cache = root / "cache"
            cache.mkdir()
            symbols = {}
            for symbol, frame in prices.items():
                path = symbol_path(cache, symbol)
                frame.loc[:settings.end].reset_index().to_csv(path, index=False)
                symbols[symbol] = dict(file=path.name, sha256=sha256(path))
            (cache / "manifest.json").write_text(json.dumps(dict(
                requested_end_exclusive=str((pd.Timestamp(settings.end) + pd.Timedelta(days=1)).date()),
                symbols=symbols, exclusions={}, failures=[])))
            argv = ["--events-source", str(sources / "events.csv"), "--suppliers-source", str(sources / "suppliers.csv"),
                    "--mapping", str(sources / "map.csv"), "--status-source", str(sources / "status.csv"),
                    "--cache", str(cache), "--output", str(root / "reports")]
            with patch.object(pipeline, "ROOT", root), patch.object(pipeline, "Settings", return_value=settings):
                pipeline.main(argv)
            bundles = list((root / "reports").iterdir())
            self.assertEqual(len(bundles), 1)
            self.assertEqual(len(list(bundles[0].glob("primary/*/costs*/metrics.json"))), 4)
            self.assertTrue((bundles[0] / "primary/comparison_costs1.json").exists())
            # All logs/results belong to the temporary fixture repo, never the real trial log.
            self.assertTrue((root / "results/variants_log.csv").exists())

    def test_webull_daily_bars_map_to_new_york_session_dates(self):
        from types import SimpleNamespace

        from backfill.prices import fetch_webull

        records = [  # one bar stamped at the US close, one at UTC midnight (the next NY evening)
            dict(time="2020-01-02T21:00:00.000+0000", open="10", high="11", low="9", close="10.5", volume="100"),
            dict(time="2020-01-04T00:00:00.000+0000", open="10.5", high="12", low="10", close="11", volume="200"),
        ]
        response = SimpleNamespace(status_code=200, json=lambda: {"result": [{"symbol": "TEST", "result": records}]})
        client = SimpleNamespace(market_data=SimpleNamespace(get_batch_history_bar=lambda **kw: response))
        bars = fetch_webull(client, "TEST", "2020-01-01", "2020-01-10")
        self.assertEqual([str(d.date()) for d in bars.date], ["2020-01-02", "2020-01-04"])
        self.assertTrue((bars.adj_close == bars.close).all())
        self.assertEqual(list(bars.columns), COLUMNS)

    def test_cross_check_flags_misaligned_series_and_measures_dividend_gap(self):
        from backfill.prices import cross_check

        days = pd.bdate_range("2020-01-01", periods=300)
        rng = np.random.default_rng(1)
        returns = rng.normal(0, 0.01, len(days))
        reference = pd.DataFrame(dict(date=days, adj_close=100 * np.cumprod(1 + returns)))
        # Same moves without a 3%/year dividend accrual: aligned, but a measurable gap.
        no_dividends = reference.assign(adj_close=reference.adj_close * np.exp(-0.03 * np.arange(len(days)) / 252))
        good = cross_check(no_dividends, reference)
        self.assertTrue(good["ok"])
        self.assertAlmostEqual(good["annualized_log_return_gap"], -0.03, delta=0.005)
        shifted = reference.assign(date=reference.date + pd.offsets.BDay(1))  # one-session misalignment
        self.assertFalse(cross_check(shifted, reference)["ok"])

    def test_failed_cross_check_falls_back_to_yahoo_and_is_recorded(self):
        from backfill import prices

        days = pd.bdate_range("2013-01-02", periods=300)
        rng = np.random.default_rng(2)

        def series(n=len(days)):
            close = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
            return pd.DataFrame(dict(date=days[:n], open=close, high=close * 1.01, low=close * 0.99, close=close,
                                     adj_close=close, volume=1000.0, dividends=0.0, splits=0.0))[COLUMNS]

        yahoo = {s: series() for s in ["GOOD", "GAPPY", "SPY", "^GSPC"]}
        webull = {"GOOD": yahoo["GOOD"], "SPY": yahoo["SPY"], "GAPPY": yahoo["GAPPY"].iloc[::4].reset_index(drop=True)}
        events = pd.DataFrame(dict(ticker=["GOOD", "GAPPY"], country="US", benchmark="SPY"))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(prices, "webull_client", return_value=object()), \
                patch.object(prices, "fetch_webull", side_effect=lambda c, s, a, b: webull[s]), \
                patch.object(prices, "fetch_yahoo", side_effect=lambda s, a, b: yahoo[s]):
            manifest = prices.fetch_cache(events, Path(tmp) / "cache", start="2013-01-01", end="2014-03-01")
        entries = manifest["symbols"]
        self.assertEqual(entries["GOOD"]["vendor"], "webull")
        self.assertTrue(entries["GOOD"]["cross_check"]["ok"])
        self.assertEqual(entries["GAPPY"]["vendor"], "yfinance")
        self.assertIn("failed cross-check", entries["GAPPY"]["fallback_reason"])
        self.assertEqual(entries["^GSPC"]["vendor"], "yfinance")  # indices are never Webull
        self.assertEqual(manifest["failures"], [])

    def test_holdout_is_always_primary_and_other_variants_are_only_disclosed(self):
        from backfill.selection import choose

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant, sharpe, p_value, status in [("primary", .5, .2, "completed"),
                                                     ("capture60", .8, .3, "completed"),
                                                     ("hold40", .7, .01, "completed"),
                                                     ("hold20", .9, .2, "failed")]:
                bundle = root / variant
                bundle.mkdir()
                (bundle / "identity.json").write_text(json.dumps(dict(
                    settings={"final": False}, selected_variant=variant, files={}, diagnostic_leave_out=None)))
                (bundle / "status.json").write_text(json.dumps({"status": status}))
                for role in ["winner", "placebo"]:
                    for multiplier in [1, 2]:
                        directory = bundle / variant / role / f"costs{multiplier}"
                        directory.mkdir(parents=True)
                        (directory / "metrics.json").write_text(json.dumps(dict(sharpe=sharpe,
                                                                                inference={"p_value": p_value})))
            record = choose(root)
            # A higher in-sample Sharpe with a passing placebo gate must not switch the holdout spec.
            self.assertEqual(record["selected"]["variant"], "primary")
            disclosed = {d["variant"]: d for d in record["disclosed_variants"]}
            self.assertEqual(set(disclosed), {"primary", "capture60", "hold40"})  # failed bundle excluded
            self.assertFalse(disclosed["hold40"]["placebo_gate_passed"])


if __name__ == "__main__":
    unittest.main()
