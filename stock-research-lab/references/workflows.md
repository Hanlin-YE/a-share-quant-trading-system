# Stock Research Lab Workflows

This reference adapts the useful LLMQuant-style workflows into local Codex usage. Prefer user-provided data, local project scripts, official filings, exchange/company sources, and clearly cited web data when freshness matters.

## 1. Evidence Contract

Use this contract for every workflow:

- Normalize ticker, market, horizon, benchmark, and requested decision.
- Identify data windows before analysis: filing period, price range, observation date, event date, and source.
- Keep a `Data Used / Missing` block. Missing data is not a weakness to hide; it is an input to risk.
- Separate facts, assumptions, and interpretation.
- Do not provide a numeric valuation, score, ownership claim, or estimate unless the source or user data supports it.

## 2. Five-Lens Stock Analysis

Use when the user asks for a stock view, score, "怎么看", or a compact but rigorous analysis.

Score each lens 0-10:

- **Fundamentals**: growth quality, margins, ROE/ROIC, leverage, FCF conversion.
- **Valuation**: absolute multiples, peer/history comparison, FCF yield vs rates, margin of safety.
- **Technicals**: trend, moving averages, RSI/KDJ/MACD, ATR risk, support/resistance.
- **Sentiment / Regime**: market risk appetite, sector rotation, event pressure, volatility backdrop.
- **Flow / Ownership**: institutional sponsorship, crowding, volume anomaly, northbound/fund flow if available.

Output:

1. Recommendation band, composite score, confidence.
2. Five-lens table with score, evidence, and data date.
3. Bull case and bear case.
4. Target/stop/review framework, not an unconditional trade.
5. Data used and missing inputs.

Guardrails:

- Do not show a score without the evidence behind it.
- If ownership, estimates, or filings are unavailable, mark those lenses data-limited.
- For A shares, prefer `stock-analyzer/scripts/analyze.py` for the technical/ML lens.

## 3. Equity Research Memo

Use when the user asks for a deeper report, company memo, or investment thesis.

Procedure:

1. Clarify ticker, horizon, and framing: bullish, bearish, neutral, or watchlist.
2. Gather primary evidence first: filings, annual/interim reports, company announcements, business description, risks, MD&A/经营分析.
3. Add market context: price trend, drawdown, volatility, sector/peer performance.
4. Add ownership/crowding only if data is available.
5. Build the memo from evidence before interpretation.

Output:

1. Rating / View.
2. Thesis summary, 3-5 evidence-backed bullets.
3. Business quality.
4. Financial / filing evidence.
5. Market context.
6. Ownership / crowding if available.
7. Key risks.
8. Variant perception.
9. Data used / missing.

## 4. Watchlist Monitor

Use when the user wants an observation list, daily watch, "keep an eye on", or a dashboard.

State operations:

- Add/remove/list only when the user asks.
- Use `scripts/research_state.py watchlist ...` for local records.

Monitoring procedure:

1. List tickers and notes.
2. Pull or request current price/volume/events if needed.
3. Rank attention by urgency: event today, price break, volatility spike, score change, stale thesis, missing alert.
4. Present dashboard first, then ticker details.

Output:

1. Watchlist summary.
2. Ticker table: price/move/status if available.
3. Priority alerts and reason.
4. Suggested next check.
5. Data used / stale items.

## 5. Investment Thesis Tracker

Use when the user wants buy logic, sell conditions, thesis review, or position tracking.

Procedure:

1. Clarify create/review/update/close.
2. Convert free-form buy logic into concise thesis bullets.
3. Convert exit logic into structured sell conditions:
   - price drop from cost, peak, or thesis date;
   - valuation ceiling or margin-of-safety loss;
   - growth/margin/leverage/FCF deterioration;
   - event breach such as guidance cut, product failure, regulatory action;
   - manual qualitative breach text.
4. If current data cannot evaluate a condition, mark it `unknown`, not `pass`.
5. Store only on explicit user request.

Output:

1. Thesis status: active, triggered, closed, missing.
2. Buy thesis.
3. Sell conditions with threshold/source.
4. Current check: pass/fail/unknown.
5. Actions: update, close, investigate trigger, refresh evidence.

## 6. Take-Profit Lab

Use when the user asks whether to hold, trim, stop, take profit, or avoid giving back gains.

Procedure:

1. Define cost basis, position size, horizon, tax/fee constraints if relevant.
2. Compare rules:
   - buy-and-hold;
   - tiered exits at gains;
   - full-sale trigger;
   - trailing stop;
   - volatility/ATR-aware exit;
   - hedge plus hold.
3. Compare path pain, not just CAGR: max drawdown, profit giveback, rollercoaster rate, win rate, tail outcomes.
4. Translate the chosen rule into concrete levels if cost/current price is known.

Guardrails:

- Do not optimize to one best historical rule without showing alternatives.
- Use adjusted prices when simulating exits.
- For high-volatility instruments, discuss path dependency.

## 7. Research Health Check

Use when the user asks to review the research workspace or "看看还有哪些研究要更新".

Procedure:

1. Load watchlist and thesis state.
2. Group issues:
   - stale profile/evidence;
   - thesis drift;
   - triggered sell condition;
   - orphan theme/watchlist item;
   - missing monitor or alert;
   - outdated data date.
3. Rank by urgency and actionability.
4. Mutate nothing unless asked.

Output:

1. Overall score 0-100 and report date.
2. Issue counts.
3. Top actions.
4. Detailed findings by category.
5. Data used / missing.

## 8. Theme Research

Use for thematic equity baskets: AI infrastructure, high dividend, EV chain, semiconductor, low-altitude economy, etc.

Procedure:

1. Normalize theme name, tickers, keywords, and benchmark.
2. Draft a provisional basket when the user gives only a vague theme; label it provisional.
3. Analyze performance, valuation/quality outliers, concentration, overlap, and event feed.
4. For A-share daily theme tables, route to `stock-analyzer/scripts/theme_scan.py` first.

Output:

1. Theme snapshot.
2. Top movers / laggards.
3. Valuation / quality summary.
4. Event feed.
5. Add/remove/monitor actions.

Guardrails:

- Do not call a theme diversified if one or two names dominate.
- Do not include event/news claims without dates and source metadata.

## 9. Macro / Event Impact

Use for earnings, policy, macro shock, rates, FX, oil, credit, or liquidity impact on a watchlist/portfolio.

Procedure:

1. Define scope: holdings/watchlist/proxy basket, benchmark, horizon, and shock/event.
2. Map sensitivities: growth, rates, inflation, currency, commodity, credit, volatility, liquidity.
3. Identify likely winners, losers, hedges, and concentration risks.
4. Produce monitors and thresholds.

Guardrails:

- Do not calculate portfolio impact without holdings, weights, or a stated proxy.
- Separate pre-event setup from post-event conclusion.

## 10. Investor Scorecards

Use as overlays, not persona cosplay.

Available scorecards:

- Buffett-style: simple business, durable moat, management/capital allocation, valuation discipline.
- Graham-style: balance sheet, earnings stability, valuation discount, margin of safety.
- Lynch-style: understandable growth, unit economics, runway, valuation relative to growth.
- Damodaran-style: story-to-numbers bridge, drivers, scenario valuation, uncertainty.
- Taleb/Marks-style: fragility, cycle position, tail risk, offense/defense posture.

Guardrails:

- Never imply a named investor would buy the stock.
- Score with evidence; do not use reputation or anecdotes as substitutes.
