"""Translate saved research artifacts into explicit display records. No backtests."""
import csv
import hashlib
import json
import math
from pathlib import Path

from dashboard.archive import archive_index, wayback_url


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def document(path):
    return json.loads(path.read_text()) if path.exists() else {}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class ResearchRepository:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.frozen = self.root / "data/processed/final_candidate/v1"
        latest = document(self.root / "results/research/final_candidate_v1_20261004/latest.json")
        self.run = self.root / latest.get("directory", "results/research/missing")
        if not self.run.resolve().is_relative_to(self.root):
            raise ValueError("Research run must be inside the repository")
        self.basket = document(Path(__file__).parent / "data/reported_basket.json")
        self.archive = archive_index(rows(self.root / "data/processed/index_detail.csv"))

    def scenario(self, strategy="candidate", costs=1, vendor="reference_mix"):
        if strategy not in {"candidate", "primary", "basket"}:
            raise ValueError("Unknown strategy")
        if costs not in (1, 2) or vendor not in {"reference_mix", "webull_only"}:
            raise ValueError("Unknown cost or vendor policy")
        if strategy == "basket":
            if vendor == "webull_only":
                return dict(id=strategy, available=False, reason="No Webull-only basket run is supplied")
            selected = {r["run_id"].split("/")[-2]: r for r in self.basket.get("runs", [])
                        if r["run_id"].endswith(f"costs{costs}")}
            winner = selected.get("winner", {})
            return dict(id=strategy, name="Injectable specialist basket", classification="Exploratory · reported",
                        available=bool(winner), metrics=winner.get("metrics", {}),
                        controls=selected.get("placebo", {}).get("metrics", {}), equity=[], control_equity=[],
                        lots=[], capacity=[], concentration=[], comparison={},
                        reason="Exact frozen Yahoo price cache and daily basket outputs are not supplied locally.",
                        vendor="Yahoo / yfinance", source=self.basket.get("source_file"),
                        source_commit=self.basket.get("source_commit"),
                        source_hash=self.basket.get("source_sha256"), run_id=winner.get("run_id"),
                        rules=["Eligible injectable shortages", "Active US specialist basket; product supply not verified for every member",
                               "Next eligible close · 60-session hold", "SPY hedge · prior 250-return beta",
                               "40% requested event capital before caps", "Unpriced exclusions are redistributed"])
        if strategy == "primary":
            if costs != 1 or vendor != "reference_mix":
                return dict(id=strategy, available=False, reason="This primary reference only supplies ordinary-cost mixed-vendor metrics")
            path = self.frozen / "primary_reference_metrics.json"
            return dict(id=strategy, available=path.exists(), name="Historical supplier primary",
                        classification="Historical primary reference", metrics=document(path), controls={},
                        equity=[], control_equity=[], lots=[], capacity=[], concentration=[], comparison={},
                        vendor="Webull + recorded Yahoo fallbacks", source=str(path.relative_to(self.root)),
                        source_hash=digest(path), reason="Daily primary reference outputs are not included in this snapshot.",
                        rules=["At least one available, unallocated presentation", "Next eligible close · 60-session hold",
                               "SPY hedge · prior 250-return beta", "5% event capital; clipped allocations stay cash"])
        folder = self.run / vendor / "delay20_hold5" / f"costs{costs}"
        path = folder / "winners/metrics.json"
        result = dict(id=strategy, name="Strict supplier · delayed entry", classification="Exploratory · saved outputs",
                      available=path.exists(), metrics=document(path), controls=document(folder / "controls/metrics.json"),
                      comparison=document(folder / "winner_minus_control.json"),
                      vendor="Webull only" if vendor == "webull_only" else "Webull + recorded Yahoo TEVA fallback",
                      source=str(path.relative_to(self.root)), source_hash=digest(path),
                      run_id=self.run.name,
                      rules=["Every listed presentation available, unallocated and nonempty",
                             "Next eligible close + 20 additional sessions", "Exit 5 sessions after entry",
                             "SPY hedge · prior 250-return beta", "5% event capital; rejected allocations stay cash"])
        for key, filename in [("equity", "equity.csv"), ("lots", "lots.csv"), ("capacity", "capacity.csv"),
                              ("concentration", "company_concentration.csv")]:
            result[key] = rows(folder / "winners" / filename)
        result["control_equity"] = rows(folder / "controls/equity.csv")
        for lot in result["lots"]:
            lot["archive_url"] = self.archive_url(lot)
        return result

    def archive_url(self, row):
        # Match on capture time AND drug: one archive second can hold several drug pages.
        return wayback_url(self.archive, row.get("capture_ts", ""), row.get("ai_key", ""))

    def overview(self):
        manifest = document(self.frozen / "price_manifest.json")
        freeze = document(self.frozen / "freeze.json")
        checks = []
        for name, expected in freeze.get("frozen_files", {}).items():
            actual = digest(self.root / name)
            checks.append(dict(file=name, expected=expected, actual=actual,
                               status="match" if actual == expected else "missing" if actual is None else "changed"))
        source_events = rows(self.root / "data/processed/shortage_events.csv")
        flags = ("date_uncertain", "left_censored", "rename_window", "spike_week", "rename_suspect")
        return dict(schema_version=1,
                    strategies=[{k: v for k, v in self.scenario(name).items()
                                 if k not in {"equity", "control_equity", "lots", "capacity", "concentration"}}
                                for name in ("candidate", "primary", "basket")],
                    coverage=dict(events=len({r["event_id"] for r in source_events}),
                                  supplier_rows=len(rows(self.root / "data/processed/suppliers.csv")),
                                  flags={f: sum(r.get(f, "").lower() == "true" for r in source_events) for f in flags}),
                    manifest=manifest, frozen_checks=checks,
                    verification=document(self.run / "verification.json"),
                    summary=rows(self.run / "summary.csv"),
                    omissions=rows(self.frozen / "prior_omissions.csv"),
                    protected_period=dict(start="2024-10-01", end="2026-10-01", status="Previously inspected",
                                          explanation="This period was inspected during prior research. Refined candidates have no new blind out-of-sample claim."),
                    limits=dict(name=.08, country=.30, sector=.50, gross=1.50, net=.25, event=.05,
                                adv=.01, drawdown=.10, restore_sessions=20),
                    reproduction="uv run python -m research.final_candidate.run",
                    notices=["Timing and basket variants are exploratory; disclose all prior searches.",
                             "AMRX contributes approximately 87% of the delayed-entry candidate's net profit.",
                             "FDA-page absence does not prove a control cannot manufacture the product.",
                             "ADV capacity is a participation bound; market impact is not calibrated."])

    def case_study(self):
        """Previously evaluated case, never an instruction to unlock or rerun OOS."""
        path = Path(__file__).parent / "data/helene_case.json"
        result = document(path)
        if not result:
            raise KeyError("Case study is not supplied")
        return dict(result, bundle_sha256=digest(path))

    def evidence(self, query="", ticker="", role="", offset=0, limit=15):
        data = rows(self.frozen / "all_candidates.csv")
        data = [r for r in data if (not query or query.casefold() in
                " ".join([r.get("product", ""), r.get("company", ""), r.get("ticker", "")]).casefold())
                and (not ticker or r.get("ticker") == ticker) and (not role or r.get("role") == role)]
        data.sort(key=lambda r: (r.get("public_date", ""), r.get("ticker", "")), reverse=True)
        for row in data:
            row["archive_url"] = self.archive_url(row)
        return dict(total=len(data), offset=offset, limit=limit, rows=data[offset:offset + limit],
                    tickers=sorted({r["ticker"] for r in rows(self.frozen / "all_candidates.csv")}))

    def event(self, event_id, ticker):
        data = [r for r in rows(self.frozen / "all_candidates.csv") if r.get("event_id") == event_id]
        selected = next((r for r in data if r.get("ticker") == ticker), None)
        if selected is None:
            raise KeyError("Event/company not found")
        for row in data:
            row["presentations"] = json.loads(row.get("evidence") or "[]")
            row["archive_url"] = self.archive_url(row)
        executed = [r for r in self.scenario()["lots"] if r.get("event_id") == event_id and r.get("ticker") == ticker]
        return dict(selected=next(r for r in data if r.get("ticker") == ticker), suppliers=data,
                    executions=executed,
                    audit=[r for r in rows(self.frozen / "audit.csv") if r.get("event_id") == event_id
                           and r.get("ticker", ticker) == ticker])

    def explanation(self, trade_id):
        """Cached Gemini summary from scripts/explain_trades.py; never generated on request."""
        cache = document(self.root / "results/explanations.json")
        entry = cache.get("explanations", {}).get(trade_id)
        if entry is None:
            raise KeyError("Explanation not available")
        source = cache.get("source")
        return dict(trade_id=trade_id, text=entry["text"], facts=entry["facts"], model=cache.get("model"),
                    generated_at=cache.get("generated_at"), label="AI-generated summary of the facts above",
                    source=source, current=bool(source) and digest(self.root / source) == cache.get("source_sha256"))

    def download(self, name, costs=1, vendor="reference_mix"):
        if costs not in (1, 2) or vendor not in {"reference_mix", "webull_only"}:
            raise ValueError("Unknown scenario")
        folder = self.run / vendor / "delay20_hold5" / f"costs{costs}"
        allowed = {"events.csv": self.frozen / "all_candidates.csv",
                   "helene_case.json": Path(__file__).parent / "data/helene_case.json",
                   "manifest.json": self.frozen / "price_manifest.json",
                   "summary.csv": self.run / "summary.csv", "freeze.json": self.frozen / "freeze.json",
                   "lots.csv": folder / "winners/lots.csv", "equity.csv": folder / "winners/equity.csv",
                   "trades.csv": folder / "winners/trades.csv", "capacity.csv": folder / "winners/capacity.csv",
                   "controls.csv": folder / "controls/equity.csv", "factors.csv": self.frozen / "factors.csv"}
        if name not in allowed or not allowed[name].is_file():
            raise KeyError("Download not available")
        return allowed[name]
