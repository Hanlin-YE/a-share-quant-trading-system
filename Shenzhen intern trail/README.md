# Shenzhen intern trail

Independent A-share stock screening system prototype.

This folder is intentionally separate from the existing `stock-analyzer`,
`stock-research-lab`, and `trading-journal` flows. It does not read or write
the old paper-trading ledgers.

## Goal

Build a four-layer screening pipeline:

1. News and trend scan every 30 minutes: Jin10, Wind, Baidu hot search, Google
   Trends top 10, official media, and other configured sources. The prototype
   accepts normalized local news JSON and extracts hot stocks/themes.
2. Technical and risk filter: keep candidates with possible main-force
   accumulation, remove high-risk names.
3. Volume and large-order filter: require breakout volume, or volume moving
   averages `4 > 11 > 117`, plus strong large-order participation.
4. Buy-plan layer: target the most likely follow-buy stock as dragon two
   (`leader_rank=2`). Emit A-class breakout, B-class breakout, or board-chasing
   7-8% limit-order setup only when at least one stock in the same sector/theme
   has already hit limit-up. If dragon two is already fast sealed and cannot be
   bought, fall back to dragon three (`leader_rank=3`) in the same theme.

The current implementation is a local, testable skeleton. Real Wind access,
Jin10 crawling, Google Trends access, and brokerage order placement are not
enabled by default.

## Quick Start

```bash
python -m src.cli run \
  --news data/examples/news_items.json \
  --market data/examples/market_snapshot.csv \
  --out data/examples/latest_run.json
```

Daily update:

```bash
python -m src.cli daily
```

This writes:

- `runs/YYYY-MM-DD/latest.json`
- `runs/latest.json`

Run tests:

```bash
python -m unittest discover -s tests
```

## Data Contracts

`news_items.json` is a list of objects:

```json
{
  "source": "official_media",
  "title": "AI算力政策催化",
  "summary": "算力、液冷、光模块方向活跃",
  "published_at": "2026-06-25T09:30:00+08:00"
}
```

`market_snapshot.csv` contains one row per stock:

```csv
code,name,themes,pct_change,close,volume,volume_ma4,volume_ma11,volume_ma117,large_order_ratio,main_force_net,turnover,risk_flags,breakout_a,breakout_b,is_limit_up,is_fast_sealed,leader_rank
```

Important fields:

- `themes`: `|` separated theme words.
- `risk_flags`: `|` separated risk tags such as `st`, `suspension`, `major_litigation`, `earnings_warning`, `regulatory_probe`.
- `large_order_ratio`: decimal ratio, for example `0.18` means 18%.
- `main_force_net`: net main-force capital flow. Positive is preferred.
- `breakout_a` and `breakout_b`: boolean-like values: `true/false`, `1/0`, `yes/no`.
- `is_limit_up`: whether this stock is the same-sector limit-up anchor.
- `is_fast_sealed`: whether the stock has rapidly sealed limit-up and is not realistically buyable.
- `leader_rank`: current same-theme ladder rank, where `1` is dragon one, `2` is dragon two, and `3` is dragon three.

## Output

The CLI writes JSON with:

- `hot_pool`: stocks linked to news themes.
- `layer_results`: per-layer pass/fail details.
- `buy_plans`: non-executable order plans with trigger type, limit price, and risk notes.

## Risk Boundary

This project is research tooling only. It does not constitute investment
advice and does not place orders. Before any real capital use, add verified
data-source adapters, replay tests, transaction-cost modeling, T+1 rules,
limit-up/limit-down handling, cancellation logic, and manual approval gates.
