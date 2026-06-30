# Trading Journal

这个目录单独存放每日交易与复盘数据，和 `stock-analyzer` / `stock-research-lab` 的研究代码分开。

目标是把交易事实收拢到一张表里沉淀：

1. 当天组合是什么
2. 每只股票当前还持有什么
3. 当日买卖、成本、盈亏和总资产如何变化
4. 一段时间后回头看，哪些策略有效、哪些需要降权或淘汰

唯一正式提交表格是已有工作簿 `量化交易AI实盘_纸面交易记录.xlsx`。以后所有交易信息更新、
审计、复核和流程检查，只能使用这一个工作簿：要么填补已有 sheet，要么在这个工作簿内新增 sheet。
不再生成新的 `.xlsx` 表格作为提交物。底层机器可读事实源仍是 `portfolio_ledger.csv`，但对人审计时
必须同步回同一个工作簿。

`交易总表` sheet 中所有日期都在同一个 sheet 里向下追加，通过 `row_type` 区分：

- `DAY_SUMMARY`: 每日总资产、现金、股票市值、当日盈亏、总暴露、回撤和风险状态
- `POSITION`: 当日每只股票持仓、成本、最新价、市值、权重和浮盈亏
- `TRADE`: 当日买卖流水、成交金额、佣金、印花税、净现金流、策略标签和原因
- `STRATEGY_FEEDBACK`: 根据过往交易和流水线结果更新策略权重、状态和淘汰原因

`ledger/orders.csv`、`ledger/positions.csv`、`ledger/equity_curve.csv` 仅作为兼容导出，不能再作为新的交易事实源扩展。

显示规范：

- `方向` / `动作` 不混用英文和中文。工作簿展示层统一为 `买入`、`卖出`、`持有`、`观察`、`研究` 等中文标签。
- `判断状态` 使用固定中文枚举：`已成交`、`持仓中`、`已完成`、`待处理`、`失败`、`已豁免`、`逾期未留证`。不再在工作簿中展示 `filled`、`open`、`completed` 或长期停留的 `待验证`。
- 已过复核时点但没有后验证据的历史项，不标成完成；统一标为 `逾期未留证`，并在备注保留原始待验证条件，后续通过流程检查账本补审。
- `期初权益`、`期末权益/总资产`、`当日盈亏`、`当日收益率%` 是正式纸面账户口径，只允许 `DAY_SUMMARY` / `组合汇总` 行填充。
- `BACKTEST` / `回测` 行不得占用正式账户权益列，避免把回测初始资金和回测期末权益误读成账户连续净值。日常盘后默认记录风险监控和漂移检查；研究回测只在策略代码、参数、股票池规则变更或周/月度复盘时运行。
- 第二天 `期初权益` 必须等于前一个正式 `DAY_SUMMARY` 的 `期末权益/总资产`；不一致时先修账，不继续提交审计。
- 工作簿内的 `账户口径说明` sheet 用来解释正式纸面账户与回测结果的桥接关系。回测的 `总收益` 或 `期末权益`
  是历史策略模拟结果，不是当天纸面账户收益，不得和 `组合汇总` 的总资产直接相加或比较。

推荐工作流：

1. 盘前：先生成当天流程检查点，再在 `daily/` 新建当天日志，写计划、观察点、无效条件。
2. 盘中/盘后：把成交、调仓、止损、撤单通过 `paper_account.py trade` 写入 `portfolio_ledger.csv`，并把对应复查点标记为完成或失败。
3. 收盘后：通过 `paper_account.py settle` 在同一张表下方追加/更新每日组合、持仓、盈亏和风险状态。
4. 复盘：审计当天流程检查点；策略治理器把反馈写回 `STRATEGY_FEEDBACK` 行，失败策略降权、暂停或淘汰。

P0 账户闭环已经接入 `stock-analyzer/scripts/paper_account.py`：

```bash
python3 stock-analyzer/scripts/paper_account.py init
python3 stock-analyzer/scripts/paper_account.py trade --date 2026-06-05 --time 13:00 --symbol 600000 --name 浦发银行 --side BUY --quantity 16200 --price 9.23 --reason 小仓验证 --strategy-tag stable
python3 stock-analyzer/scripts/paper_account.py settle --date 2026-06-05 --price 600000=9.34 --notes 盘后结算
python3 stock-analyzer/scripts/paper_account.py status
```

账户配置在 `account.json`，当前默认纸面资金为 `1000000` 元；成本模型包含佣金、最低佣金、卖出印花税、过户/经手类费用和滑点；风险状态会按单日亏损和最大回撤输出 `OK`、`ALERT` 或 `STOP`。运行后会同步已有 Excel：

```bash
python3 tools/sync_portfolio_workbook.py trading-journal/portfolio_ledger.csv trading-journal/量化交易AI实盘_纸面交易记录.xlsx
```

P0.5 纸面策略执行决策已经接入 `stock-analyzer/scripts/paper_execute.py`：

```bash
python3 stock-analyzer/scripts/paper_execute.py --stocks 600519,300750 --days 260 --source premium --require-cache-health
```

默认只输出 BUY / SELL / HOLD 决策包，不写账本。只有显式追加 `--execute` 时才会调用 `paper_account.py` 写入纸面成交；这仍然不是现实交易。执行层会读取 `strategies.json` 的 `active_paper_strategy_id`，没有 active 时使用 `score-standard-v1`。

P0.8 日内五阶段流水线已经接入 `stock-analyzer/scripts/daily_pipeline.py`。可以把自动化统一配置到这一个入口：

```bash
# 08:30 盘前：缓存门禁 + 可选策略优化/晋级
python3 stock-analyzer/scripts/daily_pipeline.py --stage preopen --stocks 600519,300750 --days 260 --source premium --record

# 09:30 开盘：按 active paper strategy 生成纸面执行决策
python3 stock-analyzer/scripts/daily_pipeline.py --stage open --stocks 600519,300750 --days 260 --source premium --record

# 12:00 午间：复核上午结果并生成下午计划
python3 stock-analyzer/scripts/daily_pipeline.py --stage midday --stocks 600519,300750 --days 260 --source premium --record

# 13:00 午后：按午间计划/active strategy 生成纸面执行决策
python3 stock-analyzer/scripts/daily_pipeline.py --stage afternoon --stocks 600519,300750 --days 260 --source premium --record

# 15:10 盘后：生成收盘决策包；显式 --execute 时才结算纸面账本并写运营日报
python3 stock-analyzer/scripts/daily_pipeline.py --stage close --stocks 600519,300750 --days 260 --source premium --record
```

流水线默认 dry-run，不写订单、不结算、不真实下单。只有显式追加 `--execute` 时才写入纸面账本；只有 `preopen --promote` 才允许把合格策略候选晋级为 `active_paper_strategy_id`。
追加 `--record` 后，每个阶段会写入 `pipeline-runs/<日期>/<阶段>.json`，供后续复盘、策略调参和自动化健康检查使用。

流水线反馈评估接入 `stock-analyzer/scripts/pipeline_review.py`：

```bash
python3 stock-analyzer/scripts/pipeline_review.py --date 2026-06-11
python3 stock-analyzer/scripts/pipeline_review.py --date 2026-06-11 --json
```

反馈脚本会读取五阶段 JSON、组合总表里的交易和权益行，输出失败桶：例如 `data_cache_unhealthy`、`open_failed`、`pipeline_ok`。这份反馈是后续自动调整策略的训练材料。

每日流程检查账本接入 `stock-analyzer/scripts/workflow_checkpoints.py`，用于解决 Codex 不一定在每个时段打开的问题。它会把当天应完成的盘前、开盘、10:30、午间、14:00、收盘和盘后审计步骤写入 `workflow-checkpoints.csv`。即使错过了时段，事后运行 audit 也会把未闭环项标成 `overdue`，不会让 `交易总表` 里的“待验证”长期沉没。

```bash
# 每个交易日先生成当天应完成事项
python3 stock-analyzer/scripts/workflow_checkpoints.py seed --date 2026-06-24

# 有 pipeline-runs JSON 时，自动把对应阶段标成 done/failed
python3 stock-analyzer/scripts/workflow_checkpoints.py import-pipeline --date 2026-06-24

# 事后审计：列出 pending / overdue / failed 检查点
python3 stock-analyzer/scripts/workflow_checkpoints.py audit --date 2026-06-24

# 人工补做验证后，记录证据位置
python3 stock-analyzer/scripts/workflow_checkpoints.py mark --date 2026-06-24 --checkpoint morning_review --evidence '交易总表!AM9:AM16' --notes '补做10:30复核'
```

策略治理器接入 `stock-analyzer/scripts/strategy_governance.py`：

```bash
python3 stock-analyzer/scripts/strategy_governance.py --date 2026-06-11
```

治理器会把反馈桶和账户风险状态转成下一轮权限：是否允许研究回测、是否允许参数搜索、是否允许晋级纸面策略、是否允许新增仓位。`preopen` 阶段会先读取最近一次已有流水线记录的治理结果，再检查当天缓存；数据缓存失败、流水线记录缺失或阶段失败时，不会继续自动调参。盘前流水线会把策略反馈写入 `portfolio_ledger.csv` 的 `STRATEGY_FEEDBACK` 行，并更新 `strategies.json` 里的 `paper_weight`、`strategy_status`、连续失败/成功次数；触发 `STOP` 或单日亏损超过 1% 的活跃纸面策略会先进入 `probation` 并降权，连续失败达到 3 次才淘汰。

纸面执行层遵守 `trading-rule-governance.md`：观察池不能直接成交；新开仓至少需要 `TRADE_PLAN` 状态；样本不足 `min_actionable_history` 时只输出观察；跌破退出阈值时默认分层减仓，不做无通知整仓卖出。

P1 策略版本与参数扫描已经接入 `stock-analyzer/scripts/strategy_lab.py`：

```bash
python3 stock-analyzer/scripts/strategy_lab.py --stocks 000001,000858,600000,300750,600519 --days 360 --source auto --output trading-journal/strategy-runs/latest.csv
```

策略注册表在 `strategies.json`，当前包含 `score-standard-v1`、`score-conservative-v1`、`score-active-v1`。每次策略对比会输出收益、回撤、胜率、Sharpe、交易次数和平均仓位。

参数优化模式使用训练/验证/测试三段切分。候选参数只按验证集排序，测试集只用于样本外复核，避免用测试集挑策略：

```bash
python3 stock-analyzer/scripts/analyze.py --cache-health --cache-stocks 000001,000858,600000,300750,600519 --days 720
python3 stock-analyzer/scripts/strategy_lab.py --stocks 000001,000858,600000,300750,600519 --days 720 --source auto --optimize --require-cache-health --output trading-journal/strategy-runs/optimized.csv --recommendation-output trading-journal/strategy-runs/recommendation.json
```

`recommendation.json` 会写出推荐候选、验证/测试指标和纸面交易晋级门槛。即使候选通过门槛，也只能进入纸面交易观察，不允许自动真实下单。如果行情源、缓存和兜底全部失败，命令会以失败状态退出，不会把“全候选失败”的空结果当成有效策略优化。
参数优化会同时比较多个评分族 `score_profile`：`balanced`、`trend`、`mean_reversion`。可以用 `--score-profiles balanced,trend,mean_reversion` 指定搜索范围。不同评分族仍共用同一套样本外门槛，不会因为验证集漂亮就自动晋级。
推荐结果还包含滚动样本外评估 `walk_forward`。策略晋级不仅要求验证集和测试集通过，也要求多个滚动窗口有交易且平均收益为正；这样可以减少“单一切分刚好运气好”的过拟合。为了控制自动化耗时，默认只对排序前 `5` 个候选做滚动复核，可用 `--walk-forward-top-n` 调整。
推荐 JSON 会列出 `promotion_gate.failed_rules` 和 `next_search.actions`，用于告诉下一轮自动调参应该先扩缓存池、放宽/收紧阈值，还是进入纸面观察。
研究回测可以显式允许只用缓存健康的子集继续跑：

```bash
python3 stock-analyzer/scripts/strategy_lab.py --stocks 600519,300750 --days 260 --source auto --optimize --require-cache-health --allow-partial-cache-health --cache-max-age-hours 999999 --output trading-journal/strategy-runs/partial.csv
```

这个模式只适合研究/调试。日内纸面执行仍应使用严格全池门禁，避免遗漏持仓或候选导致错误决策。
也可以直接从本地缓存发现可回测股票池：

```bash
python3 stock-analyzer/scripts/analyze.py --discover-cache-pool --days 260 --cache-max-age-hours 999999
python3 stock-analyzer/scripts/strategy_lab.py --use-cache-pool --days 260 --source auto --optimize --require-cache-health --cache-max-age-hours 999999 --walk-forward-top-n 5 --output trading-journal/strategy-runs/cache-pool.csv
```

缓存池模式适合研究回测和调参，不适合直接作为日内执行股票池。

若需要让通过门槛的候选自动成为下一版纸面策略，可显式追加：

```bash
python3 stock-analyzer/scripts/strategy_lab.py --stocks 000001,000858,600000,300750,600519 --days 720 --source auto --optimize --require-cache-health --output trading-journal/strategy-runs/optimized.csv --recommendation-output trading-journal/strategy-runs/recommendation.json --promote-if-eligible
```

该命令只会更新 `strategies.json` 里的 `active_paper_strategy_id`，并写入 `paper-auto-optimized-v1` 纸面策略版本；不允许触发真实交易。

需要刷新本地行情快照缓存时，先跑：

```bash
python3 stock-analyzer/scripts/analyze.py --refresh-cache --cache-stocks 000001,000858,600000,300750,600519 --days 720 --source premium
```

刷新成功后再运行 `--cache-health` 和策略优化。缓存健康失败时，应先修复 DNS/行情源或接入供应商推送，不要继续自动调参。

如果外部行情源暂时不可用，也可以把供应商或手工导出的日线 CSV 导入为推送快照缓存。CSV 至少需要日期、开高低收、成交量字段，支持英文列 `date/open/high/low/close/volume` 或中文列 `日期/开盘价/最高价/最低价/收盘价/成交量`：

```bash
python3 stock-analyzer/scripts/analyze.py --import-cache-csv /path/to/600519.csv --cache-stocks 600519 --cache-stock-name 贵州茅台 --cache-provider local-csv
python3 stock-analyzer/scripts/analyze.py --cache-health --cache-stocks 600519 --days 260
```

导入缓存只解决“数据可用性”，不代表数据质量、复权一致性或策略有效性已经通过验证。

P2 运营日报已经接入 `stock-analyzer/scripts/ops_report.py`：

```bash
python3 stock-analyzer/scripts/ops_report.py --date 2026-06-07
```

日报会读取账户净值、持仓、最近交易和最新策略对比，输出到 `reviews/<日期>-ops-report.md`。

目录说明：

- `daily/`: 每日交易日志，按日期单独存档
- `portfolio_ledger.csv`: 唯一组合交易总表，所有交易事实、每日组合、持仓、盈亏、策略反馈都在这里
- `ledger/`: 兼容导出的旧结构化账本，不再作为扩展入口
- `reviews/`: 周复盘、月复盘、专题复盘
- `pipeline-runs/`: 日内五阶段流水线 JSON 记录
- `templates/`: 新建日志时直接复制使用
- `account.json`: 纸面账户资金、交易成本和风险阈值配置
- `strategies.json`: 策略版本注册表
- `strategy-runs/`: 策略批量回测对比结果

建议命名：

- 每日日志：`daily/2026-06-07.md`
- 周复盘：`reviews/2026-W23-weekly-review.md`
- 月复盘：`reviews/2026-06-monthly-review.md`

注意：

- 这里记录的是你的交易执行与复盘事实，不替代研究结论。
- 研究分析结果仍建议保留在 `stock-analyzer` / `stock-research-lab` 里，避免混杂。
