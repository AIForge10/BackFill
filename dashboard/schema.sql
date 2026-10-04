-- Explicit operator action; the dashboard never executes this migration.
-- Works on ordinary PostgreSQL; optional hypertables shown below.
CREATE SCHEMA IF NOT EXISTS backfill_live;

CREATE TABLE IF NOT EXISTS backfill_live.quotes (
    time timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    ticker text NOT NULL,
    price numeric NOT NULL CHECK (price > 0),
    previous_close numeric CHECK (previous_close > 0),
    volume bigint CHECK (volume >= 0),
    source text NOT NULL,
    PRIMARY KEY (time, ticker, source)
);
CREATE INDEX IF NOT EXISTS quotes_ticker_time ON backfill_live.quotes (ticker, time DESC);

CREATE TABLE IF NOT EXISTS backfill_live.supplier_updates (
    observed_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    event_key text NOT NULL,
    product text NOT NULL,
    company text NOT NULL,
    ticker text,
    availability text NOT NULL CHECK (availability IN ('available','allocation','disrupted','unknown')),
    source text NOT NULL,
    source_url text,
    PRIMARY KEY (observed_at, event_key, company)
);
CREATE INDEX IF NOT EXISTS supplier_updates_time ON backfill_live.supplier_updates (observed_at DESC);
-- Page-level status of an archived FDA notice (e.g. 'Currently in Shortage'); NULL for other sources.
-- Safe to re-run on an existing table.
ALTER TABLE backfill_live.supplier_updates ADD COLUMN IF NOT EXISTS status text;

-- With the TimescaleDB extension enabled, optionally run:
-- SELECT create_hypertable('backfill_live.quotes', by_range('time'), if_not_exists => TRUE);
-- SELECT create_hypertable('backfill_live.supplier_updates', by_range('observed_at'), if_not_exists => TRUE);
-- Grant the dashboard role USAGE on backfill_live and SELECT on both tables.
