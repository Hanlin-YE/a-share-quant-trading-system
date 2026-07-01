# 回测 vs 纸面交易 策略一致性审计报告

> 审计日期：2026-07-01
> 审计范围：`backtest.py`（回测路径） vs `paper_execute.py` + `daily_pipeline.py`（纸面路径）
> 结论：**发现 5 处实质差异，其中 2 处会直接导致"回测赚大钱、实盘亏成狗"**

---

## 一致性矩阵

| 维度 | 回测 (backtest.py) | 纸面 (paper_execute.py) | 一致？ | 影响 |
|------|---------------------|--------------------------|--------|------|
| 评分内核 | analyze 五件套 | analyze 五件套（同一套） | ✅ 一致 | 无 |
| 成本算法 | trade_cost_breakdown | 同一函数（import 自 backtest） | ✅ 一致 | 无 |
| **出场方式** | 清仓（0 或满仓两档） | 33% 分层减仓 | ❌ **不一致** | 高 |
| **成交时点** | T-1 信号 + T 日开盘成交 | 当日收盘价同时做信号+成交 | ❌ **不一致** | **致命** |
| **仓位公式** | 按标的数均分 | 不除以标的数 | ❌ 不一致 | 中 |
| 风控熔断 | 完全不执行 daily_loss/max_drawdown | 也不硬拦截，仅上游 governance 间接生效 | ⚠️ 都缺 | 中 |
| 策略配置源 | CLI 参数硬编码（不读 strategies.json） | 读 strategies.json | ⚠️ 双源 | 低* |
| 成本参数源 | BacktestConfig | account.json + strategies.json 双源 | ⚠️ 双源 | 低* |
| profile bonus | strategy_lab 优化时叠加 | 不叠加 | ⚠️ 潜在 | 低* |

\* 当前数值碰巧一致，但配置来源不同，未来改一处忘改另一处就会漂移。

---

## 致命差异详解

### 差异 1：成交时点——纸面存在前视偏差（look-ahead bias）

这是最严重的问题，会**系统性高估纸面收益**。

**回测（正确）** — `backtest.py:134-146`
```
previous_date = dates[idx-1]      # 信号只用到 T-1 收盘
history = frame.iloc[:previous_pos+1]
score = score_symbol_history(...)  # 用 T-1 及之前的数据评分
# 成交价取 current_date 的 open    # T 日开盘成交
trade_price = open * (1 ± slip)    # :171, :180, :214
```
信号与成交跨日，无前视，符合 T+1 现实。

**纸面（有前视）** — `paper_execute.py:115-122, 245, 256`
```
frame = ...  # 含当日数据
score = score_data_result(frame)   # 用含当日的数据评分
trade_price = score["close"]       # 当日收盘价既做信号又做成交
record_trade(price=trade_price)    # 再叠加滑点
```
**当日收盘价同时用于产生信号和成交**——这意味着策略在"知道当日收盘涨跌后"才决定是否在"那个收盘价"买入。真实交易中你无法在收盘价确定的瞬间以该价格成交（除非用集合竞价，但信号计算也需要收盘后才能完成）。

**后果**：纸面回测会比真实可执行情况看起来更好（信号已经"看到了"当天的结果），一旦上实盘，这个优势消失，表现回落。

**实证**：`open.json` 样本——决策价 40.53 → 成交价 40.5097（close - slip），确认是收盘价成交。

---

### 差异 2：出场方式——清仓 vs 分层减仓

**回测** — `backtest.py:155, 168-169`
```python
keep = {s for s in hold if signals[s][0] >= exit_score}  # 低于阈值就全卖
target_shares = 0  # 不在 keep 里就直接清仓到 0
```
只有"全卖"或"不动"两档。`strategies.json` 里定义的 `partial_exit_pct: 0.33` **回测根本不读**。

**纸面** — `paper_execute.py:219-228`
```python
if final_score < exit_score:
    action = "REDUCE"
    quantity = floor_partial_exit(current_qty, 0.33)  # 减仓 33%
    if quantity >= current_qty:
        action = "SELL"  # 剩余不足一轮才清仓
```
分层减仓，每次砍 33%，剩零股才清仓。

**后果**：两条路径的盈亏曲线完全不可比。回测里一只票跌破 45 分就清仓认错；纸面里同样情况只减 1/3，剩下 2/3 继续扛——如果该票继续下跌，纸面亏得更多；如果反弹，纸面回得更多。**回测的"最大回撤"和"胜率"指标对纸面没有预测力**。

---

## 其他差异

### 差异 3：仓位公式

**回测** `backtest.py:159-162`：
```python
target_weight = min(max_position_pct/100, max_total_exposure_pct/100 / len(target_symbols))
# 5 个标的时：min(20%, 80%/5=16%) = 16% 每只
```
按标的数均分总暴露。

**纸面** `paper_execute.py:197-201`：
```python
target_weight = min(max_position_pct, max(0, max_total_exposure_pct - exposure_pct))
# 不除以标的数，剩余暴露空间全给当前这只
```
不除以标的数。

**后果**：纸面里第一只买入的票可能拿到远超回测的仓位，资金集中度不同 → 收益波动率不同。

### 差异 4：风控熔断两边都缺

- `daily_loss_stop_pct: 1.0`、`max_drawdown_stop_pct: 10.0`（account.json）在 `paper_execute.decide_for_symbol()` 里**从未被引用**。
- 回测里 `daily_loss_stop` grep 无任何匹配，`max_drawdown` 只做事后统计不触发动作。
- 纸面仅靠 `strategy_governance` 的 `risk_state`（ALERT/STOP）在上游间接生效，但这是策略级降权，不是账户级硬熔断。

**后果**：account.json 声称的"单日亏损 1% 停止"在两套代码里都没真正执行。回测里不会因为单日大亏而暂停，纸面里也不会。

### 差异 5：配置来源双源

- 回测 `backtest.py` 的 `main()` 全用 CLI 参数 + `BacktestConfig` 硬编码默认值，**不读 strategies.json**。
- 纸面 `paper_execute.py` 读 `strategies.json` 取 `active_paper_strategy_id`。
- 成本参数：纸面 `record_trade` 读 `account.json`，但 `load_active_strategy` 又把 strategies.json 的费率塞进 BacktestConfig 却不传给 record_trade。

**当前数值碰巧一致**（entry 58 / exit 45 / fee_bps 3 / tax_bps 5 / slip 5），但来源不同。未来改 strategies.json 的阈值，回测不会跟着变，纸面会——立刻产生偏差。

---

## 修复优先级

| 优先级 | 差异 | 修复方向 | 工作量 |
|--------|------|----------|--------|
| **P0** | 成交时点前视 | 纸面改为 T 日产生信号、T+1 开盘成交（或明确标注用次日开盘） | 中 |
| **P0** | 出场方式 | 回测消费 `partial_exit_pct`，实现分层减仓，与纸面对齐 | 中 |
| P1 | 仓位公式 | 统一公式（建议回测采纳纸面的"剩余暴露"模型，或纸面采纳"均分"模型，择一） | 小 |
| P1 | 风控熔断 | 两边都补上 daily_loss_stop / max_drawdown_stop 的硬拦截 | 中 |
| P2 | 配置来源 | 回测改为从 strategies.json 读策略，消除硬编码；成本参数单一来源 | 小 |
| P2 | profile bonus | 纸面也应用 profile bonus（或回测也不叠加，保持纯 balanced） | 小 |

---

## 验证方法

修复后应跑"回测 vs 纸面"对照验证：
1. 用同一只票、同一时段、同一策略配置，分别跑回测和纸面
2. 对比每笔交易的方向、时点、数量、价格
3. 理想状态：两套路径在相同时点产生相同决策（允许成交价因滑点/timing 有微小差异）
4. 若仍有差异，逐笔 diff 定位剩余不一致点
