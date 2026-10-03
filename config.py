"""Shared settings. Change only via PR to main."""
IS_START = "2014-06-01"
OOS_START = "2024-10-01"          # holdout: never touched unless --final
OOS_END = "2026-10-01"
PRIMARY_HOLD_DAYS = 60
BETA_LOOKBACK_DAYS = 250
NEW_SHORTAGE_GAP_DAYS = 180       # product must be absent this long to count as a new event

COST_BPS_PER_SIDE = {"US": 10, "UK": 15, "DE": 15, "CH": 15, "IN": 25}
HEDGE_COST_BPS = 2

BENCHMARK = {"US": "XLV", "UK": "^FTSE", "DE": "^GDAXI", "CH": "^SSMI", "IN": "^CNXPHARMA"}

MAX_WEIGHT_PER_NAME = 0.08
MAX_WEIGHT_PER_COUNTRY = 0.30
MAX_GROSS = 1.5
MAX_ADV_PARTICIPATION = 0.05

WAYBACK_SLEEP_SEC = 1.0


def assert_in_sample(dates, final: bool = False):
    """Call on every trade date list. Blocks the holdout unless --final."""
    import pandas as pd
    d = pd.to_datetime(pd.Series(dates))
    if not final and (d >= pd.Timestamp(OOS_START)).any():
        raise RuntimeError(f"Holdout violation: dates >= {OOS_START}. Use --final only for the single OOS run.")
