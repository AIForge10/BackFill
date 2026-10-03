"""Run a historical backtest with the Webull OpenAPI data feed.
 
Configuration is read from examples/backtest/.env (never hardcode credentials).
 
    uv run python examples/backtest/main.py
 
Changes from the Webull starter (Gator Quant Hacks, Systematic Trading track):
  - Trading costs are always applied (WEBULL_COMMISSION, default 15 bp per side).
  - An out-of-sample lock refuses to load data past WEBULL_OOS_START unless
    WEBULL_ALLOW_OOS=true (set only once, after the freeze-oos git tag).
  - Extra metrics the track requires: annualized return, volatility, Sharpe,
    max drawdown and turnover, computed from the daily equity curve.
  - Every run saves results/<label>/metrics.json and equity.csv, and appends
    one row to variants_log.csv so the number of variants tested is recorded.
"""
 
from __future__ import annotations
 
import csv
import importlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
 
# Make the project importable when run as a script (python examples/backtest/main.py):
#   - PROJECT_ROOT hosts the reusable ``webull_bt`` package.
#   - the sibling ``strategies`` dir lets WEBULL_STRATEGY name a strategy by its
#     bare module name (e.g. "dual_ma"), loaded via _load_strategy_class().
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parent.parent.parent
STRATEGIES_DIR = _HERE.parent.parent / "strategies"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(STRATEGIES_DIR))
 
import backtrader as bt
import pandas as pd
from dotenv import load_dotenv
 
from webull.core.client import ApiClient
from webull.data.data_client import DataClient
 
from webull_bt.feed import WebullData
from webull_bt.logging_utils import get_logger, setup_logging
from webull_bt.visualize import RecorderAnalyzer, render_report
from webull_bt.visualize_lwc import render_report_lwc
 
 
logger = get_logger("backtest.main")
 
TRADING_DAYS_PER_YEAR = 252
 
 
def _load_strategy_class(module_name: str) -> type[bt.Strategy]:
    """Dynamically load a strategy class by its module (file) name.
 
    ``module_name`` is the strategy file's name without the ``.py``
    extension (e.g. "dual_ma" for examples/strategies/dual_ma.py). The module
    must expose a module-level ``STRATEGY_CLASS`` attribute pointing at the
    ``bt.Strategy`` subclass to run.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise SystemExit(
            f"invalid WEBULL_STRATEGY={module_name!r}: could not import module "
            f"{module_name!r} ({exc}); it must be a .py file in examples/strategies/"
        ) from exc
 
    strategy_cls = getattr(module, "STRATEGY_CLASS", None)
    if strategy_cls is None or not (
        isinstance(strategy_cls, type) and issubclass(strategy_cls, bt.Strategy)
    ):
        raise SystemExit(
            f"invalid WEBULL_STRATEGY={module_name!r}: module {module_name!r} does not "
            "define a module-level STRATEGY_CLASS pointing at a bt.Strategy subclass"
        )
    return strategy_cls
 
 
def _parse_strategy_params() -> dict:
    """Parse WEBULL_STRATEGY_PARAMS ("key=value,key2=value2") into kwargs."""
    raw = os.environ.get("WEBULL_STRATEGY_PARAMS", "").strip()
    if not raw:
        return {}
 
    params = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise SystemExit(
                f"invalid WEBULL_STRATEGY_PARAMS entry {pair!r}: expected key=value"
            )
        key, _, value = pair.partition("=")
        params[key.strip()] = _coerce_param_value(value.strip())
    return params
 
 
def _coerce_param_value(value: str):
    """Best-effort string -> int/float/bool coercion for env-sourced params."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value
 
 
def build_data_client() -> DataClient:
    """Read credentials from the environment and build a DataClient."""
    app_key = os.environ.get("WEBULL_APP_KEY")
    app_secret = os.environ.get("WEBULL_APP_SECRET")
    if not app_key or not app_secret:
        raise SystemExit(
            "missing credentials: set WEBULL_APP_KEY and WEBULL_APP_SECRET "
            "in examples/backtest/.env or the environment"
        )
 
    region_id = os.environ.get("WEBULL_REGION_ID", "us")
    api_endpoint = os.environ.get("WEBULL_API_ENDPOINT", "api.webull.com")
 
    api_client = ApiClient(app_key, app_secret, region_id)
    api_client.add_endpoint(region_id, api_endpoint)
    return DataClient(api_client)
 
 
def _parse_datetime_env(name: str, default: str | None = None) -> datetime | None:
    """Parse an optional ISO 8601 datetime from the environment (naive = UTC)."""
    raw = os.environ.get(name, default or "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(
            f"invalid {name}: {raw!r}; use ISO 8601, e.g. "
            "2026-09-15T09:30:00-04:00"
        ) from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value
 
 
def _check_oos_lock() -> None:
    """Refuse to load out-of-sample data unless explicitly allowed.
 
    The out-of-sample period starts at WEBULL_OOS_START (default 2024-10-01,
    New York time). During development WEBULL_TODATE must end before it.
    Set WEBULL_ALLOW_OOS=true only for the single final out-of-sample run.
    """
    oos_start = _parse_datetime_env("WEBULL_OOS_START", "2024-10-01T00:00:00-04:00")
    todate = _parse_datetime_env("WEBULL_TODATE")
    allow = os.environ.get("WEBULL_ALLOW_OOS", "false").strip().lower() == "true"
    if allow:
        logger.warning("[Backtest] OUT-OF-SAMPLE RUN ENABLED (WEBULL_ALLOW_OOS=true)")
        return
    if todate is None or todate >= oos_start:
        raise SystemExit(
            f"OOS lock: WEBULL_TODATE must be set and earlier than {oos_start.isoformat()}. "
            "Set WEBULL_ALLOW_OOS=true only for the one final out-of-sample run."
        )
 
 
def build_feed(data_client: DataClient, symbol: str) -> WebullData:
    """Build a single WebullData feed for ``symbol``."""
    timespan = os.environ.get("WEBULL_TIMESPAN", "D")
    category = os.environ.get("WEBULL_CATEGORY", "US_STOCK")
    count = int(os.environ.get("WEBULL_COUNT", "200"))
    fromdate = _parse_datetime_env("WEBULL_FROMDATE")
    todate = _parse_datetime_env("WEBULL_TODATE")
    if fromdate and todate and fromdate > todate:
        raise SystemExit("WEBULL_FROMDATE must be earlier than or equal to WEBULL_TODATE")
 
    return WebullData(
        dataname=symbol,
        data_client=data_client,
        category=category,
        timespan=timespan,
        count=count,
        fromdate=fromdate,
        todate=todate,
        trading_sessions="PRE,RTH,ATH,OVN",
    )
 
 
def _parse_symbols() -> list[str]:
    """Parse WEBULL_SYMBOLS (comma-separated), defaulting to AAPL."""
    raw = os.environ.get("WEBULL_SYMBOLS", "")
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return symbols or ["AAPL"]
 
 
class PortfolioStats(bt.Analyzer):
    """Records the daily equity curve and total traded value (for turnover)."""
 
    def start(self):
        self.dates = []
        self.values = []
        self.traded_value = 0.0
 
    def notify_order(self, order):
        if order.status == order.Completed:
            self.traded_value += abs(order.executed.size * order.executed.price)
 
    def next(self):
        self.dates.append(self.strategy.datetime.date(0))
        self.values.append(self.strategy.broker.getvalue())
 
    def get_analysis(self):
        return {"dates": self.dates, "values": self.values,
                "traded_value": self.traded_value}
 
 
def _portfolio_metrics(stats: dict, starting_value: float) -> tuple[dict, pd.Series]:
    """Annualized return, volatility, Sharpe, max drawdown and turnover.
 
    Turnover = total traded value (buys + sells) per year / average equity.
    Sharpe uses daily returns, a zero risk-free rate, and sqrt(252) scaling.
    """
    equity = pd.Series(stats["values"], index=pd.to_datetime(stats["dates"]))
    equity = equity[~equity.index.duplicated(keep="last")]
    if len(equity) < 2:
        return {}, equity
 
    rets = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    ann_return = (equity.iloc[-1] / starting_value) ** (1 / years) - 1
    ann_vol = rets.std() * math.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (rets.mean() / rets.std() * math.sqrt(TRADING_DAYS_PER_YEAR)
              if rets.std() > 0 else None)
    max_dd = (equity / equity.cummax() - 1).min()
    turnover = stats["traded_value"] / equity.mean() / years
 
    return {
        "period_start": str(equity.index[0].date()),
        "period_end": str(equity.index[-1].date()),
        "years": round(years, 2),
        "ann_return_pct": round(ann_return * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe_daily": round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "turnover_x_per_year": round(turnover, 2),
        "worst_day_pct": round(rets.min() * 100, 2),
    }, equity
 
 
def _compute_metrics(
    cerebro: bt.Cerebro, strat: bt.Strategy, starting_value: float
) -> dict:
    """Summary metrics shared by the text log and the HTML report."""
    final_value = cerebro.broker.getvalue()
    pnl = final_value - starting_value
    pnl_pct = (pnl / starting_value * 100.0) if starting_value else 0.0
 
    dd = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe.get("sharperatio")
 
    total_trades = trades.get("total", {}).get("total", 0)
    won = trades.get("won", {}).get("total", 0)
    lost = trades.get("lost", {}).get("total", 0)
    win_rate = (won / total_trades * 100.0) if total_trades else 0.0
    net_pnl = trades.get("pnl", {}).get("net", {}).get("total", 0.0)
 
    return {
        "starting_value": starting_value,
        "final_value": final_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "max_drawdown_pct": dd.get("max", {}).get("drawdown", 0.0),
        "max_drawdown_money": dd.get("max", {}).get("moneydown", 0.0),
        "sharpe_ratio": sharpe_ratio,
        "total_trades": total_trades,
        "won": won,
        "lost": lost,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
    }
 
 
def _print_results(strat: bt.Strategy, metrics: dict, extra: dict) -> None:
    """Log the summary report, including the track's required metrics."""
    sharpe_ratio = metrics["sharpe_ratio"]
 
    logger.info("=" * 60)
    logger.info("[Backtest] Result Summary")
    logger.info("=" * 60)
    logger.info("Starting cash    : %.2f", metrics["starting_value"])
    logger.info("Final cash       : %.2f", metrics["final_value"])
    logger.info("Net P&L          : %.2f (%.2f%%)", metrics["pnl"], metrics["pnl_pct"])
    logger.info("Max drawdown     : %.2f%% (%.2f)",
                metrics["max_drawdown_pct"], metrics["max_drawdown_money"])
    logger.info("Sharpe (bt)      : %s (annualized)",
                f"{sharpe_ratio:.4f}" if sharpe_ratio is not None else "N/A")
    logger.info("Total trades     : %d (won=%d, lost=%d, win rate=%.2f%%)",
                metrics["total_trades"], metrics["won"], metrics["lost"], metrics["win_rate"])
    logger.info("Trades net P&L   : %.2f", metrics["net_pnl"])
    logger.info("-" * 60)
    logger.info("[Track metrics, net of costs]")
    for key, value in extra.items():
        logger.info("  %-22s: %s", key, value)
    logger.info("=" * 60)
 
    closed_trades = getattr(strat, "closed_trades", [])
    if closed_trades:
        logger.info("[Backtest] Trade-by-trade detail (%d closed trade(s)):", len(closed_trades))
        for i, t in enumerate(closed_trades, start=1):
            logger.info(
                "  #%d %s %s size=%s entry=%.2f@%s exit=%.2f@%s "
                "pnl=%.2f pnlcomm=%.2f commission=%.2f bars=%d",
                i, t["symbol"], t["direction"], t["size"],
                t["entry_price"], t["open_dt"],
                t["exit_price"], t["close_dt"],
                t["pnl"], t["pnlcomm"], t["commission"], t["bars_held"],
            )
        logger.info("=" * 60)
 
 
def _save_run(label: str, extra: dict, equity: pd.Series, config: dict) -> None:
    """Save metrics + equity curve and append one row to variants_log.csv."""
    out_dir = PROJECT_ROOT / "results" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps({"config": config, "metrics": extra}, indent=2, default=str)
    )
    equity.rename("equity").to_csv(out_dir / "equity.csv", index_label="date")
    logger.info("[Backtest] saved results to %s", out_dir)
 
    log_path = PROJECT_ROOT / "variants_log.csv"
    header = ["run_id", "date", "description", "events_file", "symbols", "hold_days",
              "cost_bp", "period", "total_return_pct", "sharpe", "max_drawdown_pct",
              "turnover", "notes"]
    new_file = not log_path.exists()
    with log_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(header)
        writer.writerow([
            label,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            config["strategy"],
            config["events_file"],
            " ".join(config["symbols"]),
            config["params"].get("hold_days", ""),
            config["cost_bp"],
            f"{extra.get('period_start')} to {extra.get('period_end')}",
            config["total_return_pct"],
            extra.get("sharpe_daily"),
            extra.get("max_drawdown_pct"),
            extra.get("turnover_x_per_year"),
            "OOS" if config["oos_run"] else "in-sample",
        ])
 
 
def _maybe_render_report(
    strat: bt.Strategy, metrics: dict, strategy_module: str, symbols: list[str]
) -> None:
    """Generate the interactive HTML report unless WEBULL_VISUALIZE=false."""
    flag = os.environ.get("WEBULL_VISUALIZE", "true").strip().lower()
    if flag in ("false", "0", "no", "off"):
        logger.info("[Backtest] visualization disabled (WEBULL_VISUALIZE=%s)", flag)
        return
 
    engine = os.environ.get("WEBULL_VISUALIZE_ENGINE", "plotly").strip().lower()
    if engine == "plotly":
        renderer, default_output = render_report, "backtest_report.html"
    elif engine == "lwc":
        renderer, default_output = render_report_lwc, "backtest_report_lwc.html"
    else:
        logger.error(
            "[Backtest] invalid WEBULL_VISUALIZE_ENGINE=%r (use 'plotly' or 'lwc'); "
            "skipping visualization", engine,
        )
        return
 
    output = os.environ.get("WEBULL_VISUALIZE_OUTPUT", default_output).strip()
    output_path = Path(output)
    if not output_path.is_absolute():
        output_path = Path(__file__).resolve().parent / output_path
 
    recorded = strat.analyzers.recorder.get_analysis()
    closed_trades = getattr(strat, "closed_trades", [])
    title = f"Backtest: {strategy_module} [{', '.join(symbols)}]"
    try:
        renderer(
            recorded, closed_trades, str(output_path), title=title, metrics=metrics
        )
    except Exception:
        logger.exception("[Backtest] failed to render visualization report")
 
 
def run_backtest() -> None:
    _check_oos_lock()
    data_client = build_data_client()
 
    cerebro = bt.Cerebro()
 
    symbols = _parse_symbols()
    for symbol in symbols:
        cerebro.adddata(build_feed(data_client, symbol=symbol), name=symbol)
 
    strategy_module = os.environ.get("WEBULL_STRATEGY", "dual_ma").strip()
    strategy_cls = _load_strategy_class(strategy_module)
    strategy_params = _parse_strategy_params()
    logger.info(
        "[Backtest] strategy=%s symbols=%s params=%s",
        strategy_module, symbols, strategy_params,
    )
    cerebro.addstrategy(strategy_cls, **strategy_params)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)
 
    # Costs: every reported result is net of costs (track rule).
    # 15 bp per side by default; set WEBULL_COMMISSION=0.0030 for the costs-doubled test.
    commission = float(os.environ.get("WEBULL_COMMISSION", "0.0015"))
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=commission)
    logger.info("[Backtest] commission: %.1f bp per side", commission * 10000)
 
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    data0 = cerebro.datas[0]
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        timeframe=data0._timeframe,
        compression=data0._compression,
        riskfreerate=0.0,
        annualize=True,
    )
    cerebro.addanalyzer(RecorderAnalyzer, _name="recorder")
    cerebro.addanalyzer(PortfolioStats, _name="portfolio")
 
    starting_value = cerebro.broker.getvalue()
    logger.info("[Backtest] starting cash: %.2f", starting_value)
    results = cerebro.run(runonce=False)
    strat = results[0]
 
    metrics = _compute_metrics(cerebro, strat, starting_value)
    extra, equity = _portfolio_metrics(
        strat.analyzers.portfolio.get_analysis(), starting_value
    )
    _print_results(strat, metrics, extra)
 
    oos_run = os.environ.get("WEBULL_ALLOW_OOS", "false").strip().lower() == "true"
    label = os.environ.get("WEBULL_RUN_LABEL", "").strip() or (
        f"{strategy_module}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    config = {
        "strategy": strategy_module,
        "symbols": symbols,
        "params": strategy_params,
        "events_file": os.environ.get("SHORTAGE_EVENTS_FILE", ""),
        "cost_bp": round(commission * 10000, 1),
        "fromdate": os.environ.get("WEBULL_FROMDATE", ""),
        "todate": os.environ.get("WEBULL_TODATE", ""),
        "oos_run": oos_run,
        "total_return_pct": round(metrics["pnl_pct"], 2),
    }
    _save_run(label, extra, equity, config)
    _maybe_render_report(strat, metrics, strategy_module, symbols)
 
 
def main() -> None:
    # Load environment variables from examples/backtest/.env (python-dotenv).
    load_dotenv(Path(__file__).resolve().parent / ".env")
    setup_logging()
    run_backtest()
 
 
if __name__ == "__main__":
    main()
