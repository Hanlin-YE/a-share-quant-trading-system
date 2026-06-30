---
name: stock-research-lab
description: 股票研究生命周期 Skill。用于把股票/ETF/题材研究从一次性分析升级为可维护工作流：五维股票分析、研究备忘录、观察池监控、投资 thesis 跟踪、卖出/止盈纪律、研究健康检查、宏观/事件影响映射。适用于“写研究报告/研究备忘录/五维分析/观察池/买入逻辑/卖出条件/止盈策略/复盘/研究健康检查/主题研究/宏观影响/财报事件”等请求。默认与 stock-analyzer 配合使用，但也可基于用户提供的数据独立运行。
license: MIT
metadata:
  version: 1.0.0
  source_inspiration: LLMQuant/skills MIT workflows, adapted into local Codex workflows
---

# Stock Research Lab

## Purpose

Use this skill when the user wants durable stock research, not just a one-off price signal. It turns ideas into monitored research assets: watchlists, themes, investment theses, sell rules, event checklists, and health checks.

This skill complements `stock-analyzer`:

- Use `stock-analyzer` for numeric single-stock diagnostics and A-share theme-table scanning.
- Use `stock-research-lab` for evidence contracts, research memos, watchlists, thesis lifecycle, exit discipline, and portfolio/context overlays.

## Core Contract

1. **Evidence first**: separate retrieved/user-provided facts from interpretation. Do not fill missing financials, holdings, estimates, or event data from memory.
2. **Dates matter**: state filing period, price window, observation date, event date, data source, and stale-data caveats.
3. **Missing data is a finding**: mark unknowns explicitly; never convert an unknown trigger into a pass.
4. **Sell rules are first-class**: every bullish thesis should include invalidation, stop/review cadence, and profit-taking logic.
5. **No silent mutation**: only add/remove/update watchlist or thesis records when the user asks.
6. **Research, not advice**: outputs are decision support, not investment advice or automatic trading signals.

## Workflow Routing

Open [references/workflows.md](references/workflows.md) when you need the detailed procedure for:

- **Five-lens analysis**: fundamentals, valuation, technicals, sentiment/regime, flow/ownership.
- **Research memo**: thesis, business quality, financial evidence, market context, risks, variant perception.
- **Watchlist monitor**: summarize tracked tickers, priority changes, alerts, next checks.
- **Thesis tracker**: create/review/update/close a buy thesis with structured sell conditions.
- **Take-profit lab**: hold vs tiered exits vs trailing stop vs strict exit rules.
- **Research health check**: stale profiles, drifted theses, missing monitors, orphan themes.
- **Theme research**: thematic baskets, keywords, exposure, concentration, event feed.
- **Macro/event impact**: earnings/event setup or macro shock mapped to holdings/watchlist.
- **Investor scorecards**: Buffett/Graham/Lynch/Damodaran-style lenses as evidence-based overlays.

## Local State

Use `scripts/research_state.py` for deterministic local state under `stock-research-lab/state/`:

```bash
python scripts/research_state.py watchlist add --ticker 600519 --note "白酒龙头观察"
python scripts/research_state.py watchlist list
python scripts/research_state.py thesis add --ticker 600519 --thesis "品牌与现金流优势" --sell "ROE连续下滑或估值失去安全边际"
python scripts/research_state.py thesis list
python scripts/research_state.py health
```

If running from the installed Codex skill, use the absolute script path in `~/.codex/skills/stock-research-lab/scripts/research_state.py`.

## Output Defaults

For research deliverables, prefer this compact structure:

1. **View / Verdict**
2. **Evidence Table**
3. **Bull / Bear Case**
4. **Sell Conditions / Risk Controls**
5. **Next Checks**
6. **Data Used / Missing**

For JSON/state tasks, return parseable JSON only when the user or workflow asks for machine-readable output.
