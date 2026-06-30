# Architecture

## Boundary

`Shenzhen intern trail` is a new system, not an extension of the existing
paper-trading stack. It should keep separate config, data, tests, and runtime
outputs.

It may reuse ideas from the old project, but it must not silently read:

- `stock-analyzer/.cache`
- `trading-journal/ledger`
- `trading-journal/portfolio_ledger.csv`
- `trading-journal/量化交易AI实盘_纸面交易记录.xlsx`

## Four-Layer Pipeline

### Layer 1: News and Trend Scan

Current implementation:

- Reads normalized local JSON.
- Scores stock candidates when news title/summary contains stock name, stock
  code, or theme terms.
- Weights official media and Wind-style sources higher than generic feeds.

Production adapters needed:

- Jin10 data feed or compliant scraper.
- Wind terminal/API adapter with local credentials.
- Baidu hot search parser.
- Google Trends top-10 adapter.
- Official media RSS/API feed list.
- Scheduler that runs every 30 minutes and writes immutable scan snapshots.

### Layer 2: Technical and Risk Filter

Current implementation:

- Keeps names with positive main-force net flow and effective turnover.
- Removes hard risk flags: ST, suspension, litigation, earnings warning,
  regulatory probe, pledge risk, and delisting risk.

Production extensions:

- Add announcement and regulatory-risk ingestion.
- Add recent gap-up exhaustion, limit-up failure, and abnormal volatility
  checks.
- Add market-cap/liquidity constraints by board.

### Layer 3: Volume and Large-Order Filter

Current implementation:

- Requires either volume burst or `volume_ma4 > volume_ma11 > volume_ma117`.
- Requires large-order ratio above threshold.

Production extensions:

- Use tick/order-book data for true big-order ratio.
- Separate passive large orders, active buys, cancellations, and spoofing risk.
- Add board-specific liquidity and slippage modeling.

### Layer 4: Buy Plan

Current implementation:

- Emits A-class breakout plan if `breakout_a` is true.
- Emits B-class breakout plan if `breakout_b` is true.
- Emits board-chasing plan when current gain is 7-8%.
- Requires at least one peer in the same theme/sector to be marked limit-up
  before any follow-buy plan is emitted.
- Treats the intended follow-buy target as dragon two. If dragon two is
  `is_fast_sealed=true`, it searches the same theme for a buyable dragon three
  and emits the fallback plan instead.
- Outputs a research-only limit price. No broker API calls.

Production extensions:

- Define formal A/B breakout rules from price structure.
- Add pre-trade manual approval.
- Add order state, cancel/replace, and failed-order handling.
- Add T+1 and limit-up/limit-down constraints before any simulation or live
  execution.

## Recommended Next Build Steps

1. Add a scheduler entrypoint that writes `runs/YYYY-MM-DD/HHMM.json`.
2. Add real source adapters behind a stable `NewsSource` interface.
3. Add a market-data adapter for daily/minute bars and large-order ratios.
4. Formalize A/B breakout definitions as tested functions instead of CSV flags.
5. Add a replay backtest before connecting any broker or paper account.
