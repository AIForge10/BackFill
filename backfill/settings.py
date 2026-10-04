"""The small set of explicit rules shared by preparation and accounting."""
from dataclasses import asdict, dataclass, field

import config


@dataclass(frozen=True)
class Settings:
    start: str = config.IS_START
    end: str = "2024-09-30"  # inclusive
    hold_days: int = config.PRIMARY_HOLD_DAYS
    beta_lookback: int = config.BETA_LOOKBACK_DAYS
    event_weight: float = 0.05
    name_cap: float = config.MAX_WEIGHT_PER_NAME
    country_cap: float = config.MAX_WEIGHT_PER_COUNTRY
    sector_cap: float = 0.50  # every long is in healthcare
    gross_cap: float = config.MAX_GROSS
    net_cap: float = 0.25
    foreign_long_cap: float = 0.20
    cost_multiplier: float = 1.0
    costs_bps: dict = field(default_factory=lambda: dict(config.COST_BPS_PER_SIDE))
    hedge_cost_bps: float = config.HEDGE_COST_BPS
    hedge_carry_bps_year: float = 50.0  # assumed annual carry; stress separately
    initial_nav: float = 1_000_000.0
    drawdown_trigger: float = 0.10
    recovery_sessions: int = 20
    adv_lookback: int = 60
    adv_participation: float = config.MAX_ADV_PARTICIPATION
    final: bool = False

    def __post_init__(self):
        import math
        import pandas as pd

        if self.hold_days < 1 or self.beta_lookback < 2:
            raise ValueError("Hold days must be positive; beta needs at least two returns.")
        for key in ("event_weight", "name_cap", "country_cap", "sector_cap", "gross_cap",
                    "net_cap", "foreign_long_cap", "initial_nav", "cost_multiplier",
                    "adv_participation"):
            value = getattr(self, key)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be finite and positive.")
        if not 0 < self.drawdown_trigger < 1 or self.recovery_sessions < 1:
            raise ValueError("Invalid de-risking settings.")
        if any(not math.isfinite(v) or v < 0 for v in
               [*self.costs_bps.values(), self.hedge_cost_bps, self.hedge_carry_bps_year]):
            raise ValueError("Costs must be finite and nonnegative.")
        start, end = pd.Timestamp(self.start), pd.Timestamp(self.end)
        if start > end:
            raise ValueError("Start is after end.")
        if not self.final and end >= pd.Timestamp(config.OOS_START):
            raise ValueError("Holdout locked: in-sample accounting must end before OOS_START.")
        if self.final and (start < pd.Timestamp(config.OOS_START)
                           or end > pd.Timestamp(config.OOS_END)):
            raise ValueError("Final accounting must remain inside the registered holdout.")

    def as_dict(self):
        return asdict(self)


# FX quotes are USD per local unit; INR=X is inverted at ingestion.
FX_SYMBOL = {"US": None, "UK": "GBPUSD=X", "DE": "EURUSD=X",
             "CH": "CHFUSD=X", "IN": "INR=X"}
TIMEZONE = {"US": "America/New_York", "UK": "Europe/London", "DE": "Europe/Berlin",
            "CH": "Europe/Zurich", "IN": "Asia/Kolkata"}

# Vendor series sometimes contain predecessor history. These new securities
# must establish their own beta history; an ownership change is not an IPO.
SECURITY_START = {"AMPH": "2014-06-25", "AMRX": "2018-05-07",  # v2 branch: VTRS carries Mylan history (1:1 exchange)
                  "SDZ.SW": "2023-10-04", "GLAND.NS": "2020-11-20", "PPLPHARMA.NS": "2022-10-19"}
