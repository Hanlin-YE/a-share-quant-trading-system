from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _esc(value: Any) -> str:
    return html.escape(str(value))


def write_html_report(path: Path, result: dict[str, Any]) -> None:
    status = result.get("strict_status", "UNKNOWN")
    buy_plans = result.get("buy_plans", [])
    sell_signals = result.get("sell_signals", [])
    pools = result.get("pools_summary", {})
    portfolio = result.get("portfolio_summary", {})
    sources = result.get("source_statuses", [])

    source_items = "".join(
        f"<li><b>{_esc(s.get('source',''))}</b>: {_esc(s.get('status',''))}"
        + (f" · {_esc(s.get('error') or s.get('reason') or '')}" if s.get("error") or s.get("reason") else "")
        + "</li>"
        for s in sources
    )

    pool_entries = pools.get("entries", [])
    trade_pool = [e for e in pool_entries if e.get("layer") == "trade"]
    trade_rows = "".join(
        "<tr>"
        f"<td>{_esc(e.get('code',''))}</td><td>{_esc(e.get('name',''))}</td>"
        f"<td>{_esc(e.get('note',''))}</td><td>{_esc(e.get('last_seen_at',''))}</td><td>{_esc(e.get('days_in_pool',0))}</td>"
        "</tr>"
        for e in trade_pool
    ) or '<tr><td colspan="5">空</td></tr>'

    pos_rows = "".join(
        "<tr>"
        f"<td>{_esc(p.get('slot',''))}</td><td>{_esc(p.get('code',''))}</td><td>{_esc(p.get('name',''))}</td>"
        f"<td>{_esc(p.get('cost',''))}</td><td>{_esc(p.get('leader',''))}</td>"
        "</tr>"
        for p in portfolio.get("positions", [])
    ) or '<tr><td colspan="5">无持仓</td></tr>'

    sell_rows = "".join(
        f"<tr style='color:{'#791F1F' if s.get('urgency')=='immediate' else '#633806'}'>"
        f"<td>{_esc(s.get('code',''))}</td><td>{_esc(s.get('name',''))}</td><td>{_esc(s.get('slot',''))}</td>"
        f"<td>{_esc(s.get('urgency',''))}</td><td>{_esc(s.get('reason',''))}</td><td>{_esc(s.get('suggested_price',''))}</td>"
        "</tr>"
        for s in sell_signals
    ) or '<tr><td colspan="6">无</td></tr>'

    buy_rows = "".join(
        "<tr>"
        f"<td>{_esc(p.get('slot',''))}</td><td>{_esc(p.get('code',''))}</td><td>{_esc(p.get('name',''))}</td>"
        f"<td>{_esc(p.get('trigger',''))}</td><td>{_esc(p.get('leader_rank',''))}</td>"
        f"<td style='color:#791F1F'>{_esc(p.get('limit_price',''))}</td><td style='color:#791F1F'>{_esc(p.get('pct_change_at_plan',''))}%</td>"
        f"<td>{_esc(p.get('reason',''))}</td>"
        "</tr>"
        for p in buy_plans
    ) or '<tr><td colspan="8">无候选</td></tr>'

    market_total = result.get("market_total_amount", 0)
    degraded = result.get("degraded_news", False)

    content = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>龙头跟随实盘判断</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:24px;line-height:1.6;color:#2C2C2A;background:#fff}}
h1{{font-size:18px;font-weight:500}}h2{{font-size:15px;font-weight:500;margin-top:24px;color:#3C3489}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}td,th{{border:0.5px solid #D3D1C7;padding:6px 8px;font-size:13px;text-align:left}}
th{{background:#F1EFE8;font-weight:500;color:#5F5E5A}}
.status{{font-weight:500;padding:2px 10px;border-radius:10px;font-size:13px}}
.s-pass{{background:#EAF3DE;color:#27500A}}.s-nosignal{{background:#FAEEDA;color:#633806}}.s-blocked{{background:#FCEBEB;color:#791F1F}}
.meta{{font-size:12px;color:#5F5E5A;margin:4px 0}}
</style></head>
<body><h1>龙头跟随交易系统 · 实盘判断</h1>
<p><span class="status {'s-pass' if status=='PASS' else 's-nosignal' if status=='NO_SIGNAL' else 's-blocked'}">{_esc(status)}</span></p>
<p class="meta">时间：{_esc(result.get('run_timestamp',''))} ｜ 两市成交额：{_esc(f'{market_total/1e8:.0f}亿' if market_total else 'N/A')} ｜ 新闻降级：{_esc('是(用涨停板块热点)' if degraded else '否')}</p>

<h2>数据源状态</h2><ul>{source_items or '<li>无</li>'}</ul>

<h2>三层股池</h2>
<p class="meta">热点池 {_esc(pools.get('hot',0))} ｜ 筛选池 {_esc(pools.get('screened',0))} ｜ 交易池 {_esc(pools.get('trade',0))}（未成交满4天淘汰）</p>
<table><thead><tr><th>代码</th><th>名称</th><th>备注</th><th>最近命中</th><th>未命中天数</th></tr></thead><tbody>{trade_rows}</tbody></table>

<h2>仓位状态（分4仓滚动）</h2>
<p class="meta">已用 {_esc(len(portfolio.get('positions',[])))}/4 ｜ 空闲 {_esc(portfolio.get('free_slots',4))} 仓</p>
<table><thead><tr><th>仓位</th><th>代码</th><th>名称</th><th>成本</th><th>同板块龙一</th></tr></thead><tbody>{pos_rows}</tbody></table>

<h2>卖点信号</h2>
<table><thead><tr><th>代码</th><th>名称</th><th>仓位</th><th>紧急度</th><th>理由</th><th>建议价</th></tr></thead><tbody>{sell_rows}</tbody></table>

<h2>买入计划（研究用，不自动下单）</h2>
<table><thead><tr><th>仓位</th><th>代码</th><th>名称</th><th>触发</th><th>梯队</th><th>挂单价</th><th>涨幅</th><th>理由</th></tr></thead><tbody>{buy_rows}</tbody></table>

<h2>风险提示</h2><p class="meta">研究用途，不构成投资建议；不会自动下单。实盘需复核涨跌停、T+1、盘口撤单与当日公告风险；分4仓滚动，严格止盈止损；次日开盘10分钟不妙板即卖，龙一躺则全躺止损。</p>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
