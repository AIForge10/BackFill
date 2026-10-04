#!/usr/bin/env bash
# Reproduce the note's headline in-sample result (specialist basket, Sharpe 0.67)
# from a fresh clone, with no API keys:  bash reproduce_headline.sh
# Steps: FDA tables -> event ledger -> Yahoo prices (cached once) -> backtest.
set -euo pipefail
cd "$(dirname "$0")"
LAST=$(mktemp)

VARIANT=v2_specialist_basket
MAP=data/company_ticker_map_v2.csv
CACHE=${CACHE:-data/raw/prices/headline}
WHY="delisted before 2024; no vendor history (Webull INVALID_SYMBOL, Yahoo none); share held as disclosed exclusion"

uv run python src/05_events.py --variant "$VARIANT" --mapping "$MAP"

if [ ! -f "$CACHE/manifest.json" ]; then
  uv run python src/06_prices.py --vendor yfinance --cache "$CACHE" \
    --events "data/processed/backfill/$VARIANT/events.csv" \
    --exclude "HSP=Hospira $WHY" --exclude "AKRX=Akorn $WHY" --exclude "ENDP=Endo $WHY" \
    --exclude "IPXL=Impax $WHY" --exclude "LCI=Lannett $WHY" --exclude "SGNT=Sagent $WHY" \
    --exclude "TLGT=Teligent $WHY"
fi

uv run python run_all.py --variant "$VARIANT" --mapping "$MAP" --cache "$CACHE" | tee /dev/stderr \
  | grep -o 'results/backfill/[0-9a-f]*' | tail -1 > "$LAST"

LAST="$LAST" uv run python - <<'EOF'
import json, os
bundle = open(os.environ["LAST"]).read().strip()
for costs in ("costs1", "costs2"):
    m = json.load(open(f"{bundle}/v2_specialist_basket/winner/{costs}/metrics.json"))
    print(f"{costs}: annual return {m['annualized_return']:+.2%}  Sharpe {m['sharpe']:.2f}  "
          f"max drawdown {m['max_drawdown']:.2%}  p {m['inference']['p_value']:.3f}  "
          f"positions {m['positions']}  bundle {bundle}")
EOF
