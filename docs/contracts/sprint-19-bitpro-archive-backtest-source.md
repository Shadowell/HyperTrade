# Sprint 19 Contract: BitPro Archive Backtest Source

## Goal

Allow HyperTrade to use archived BitPro K-line data as a backtest candle source while keeping HyperTrade independent from BitPro business logic.

## Scope

- Add a BitPro SQLite K-line archive reader.
- Read BitPro tables such as `kline_1h`, `kline_4h`, and fallback `kline_history`.
- Convert BitPro rows into HyperTrade `Candle` objects.
- Add `BITPRO_SQLITE_PATH` configuration.
- Add `/backtest --source bitpro --symbol <symbol> --bar <bar> --limit <n>` support.
- Preserve existing sample and OKX live candle sources.

## Out Of Scope

- Copying BitPro strategy logic.
- Migrating all BitPro data into PostgreSQL.
- Reading BitPro parquet/csv file store.
- Live order execution.

## Acceptance

- Unit tests read a temporary BitPro-style SQLite K-line table.
- BacktestService can run with `candle_source="bitpro"`.
- CLI can pass `/backtest --source bitpro` options.
- Full `./scripts/check.sh` passes.
- Server smoke runs a BitPro archive backtest when `/opt/bitpro/data/crypto_data.db` is available.
