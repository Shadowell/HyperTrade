# OKX Testnet Order Smoke

## Preconditions

- Run on server `47.79.36.92`.
- `/opt/hypertrade/.env` contains OKX Testnet credentials.
- `OKX_TESTNET=true`.
- Use a very small order size.

## Commands

```bash
hypertrade
/live intent ETH buy 0.01 --reason testnet smoke
/live approve loi_xxx --reason checked
/live execute loi_xxx
/live intents
```

Expected:

- Intent starts as `pending_approval`.
- Approval moves it to `approved` only if RiskEngine allows it.
- Execute moves it to `executed_testnet` or `execution_failed`.
- Execution result stores redacted request data.

Never run Mainnet execution. Mainnet remains blocked by RiskEngine.

