---
name: stock-analyzer
description: 中国A股量化选股与交易辅助 Skill。输入股票代码/名称时做单票量化诊断；输入涨停分析表、题材表、资金流表或要求盯盘/题材轮动/潜力股筛选时，执行A股题材雷达流程。内化四引擎：题材轮动与潜力股过滤、技术指标与数据留痕、多视角投研证据链、回测与风控优先。触发短语："分析股票"、"股票分析"、"量化分析"、"看看这只股票"、"XX股票怎么样"、"分析一下XX"、"A股选股"、"AI盯盘"、"题材轮动"、"涨停分析"、"潜力股筛选"。
metadata:
  version: 3.0.0
  author: AI Agent
  market: 中国A股
  data_source: 专业优先模式使用供应商推送缓存/Tushare Pro，失败后回退腾讯财经 qfq 日线、东方财富与 Stooq 实验源
---

# 中国A股量化交易 Skill

## 定位

这个 Skill 是 A 股研究与选股辅助系统，不是直接下单机器人。它有两条主路径：

1. **单票诊断**：输入股票代码或名称，自动获取日线行情，把技术指标、机器学习概率、统计状态和风险约束合并成一份量化决策报告。
2. **题材雷达**：输入涨停分析表、题材表或资金流表，按题材热度识别主线，只在用户给定表格内筛选未涨停候选股，并输出稳定 JSON。

当用户要写研究备忘录、维护观察池、记录买入 thesis、设置卖出条件、做止盈实验或检查研究健康度时，搭配 `stock-research-lab` 使用；本 skill 负责量化计算与题材初筛，`stock-research-lab` 负责研究生命周期。

当前仅考虑中国 A 股市场，默认使用 `--source premium`：先读数据供应商推送缓存，再走 Tushare Pro 主动拉取，失败后回退腾讯财经前复权日线、东方财富与 Stooq 实验源。若只想使用推送缓存，用 `--source push`；若只想主动拉取，用 `--source pull`。

## 我们自己的四引擎框架

这套 Skill 已内化四类思路，但统一改写成自己的工程规范：

1. **题材轮动引擎**：从涨停归因表里统计涨停数量、题材强度、资金净额、封单强弱，找前三核心题材；只从核心题材内筛选未涨停、资金净额为正、涨幅/换手/量比达标的候选股。
2. **量价技术引擎**：用 RSI、KDJ、MACD、均线、ATR、波动率、回撤等指标诊断单票，也为批量扫描留下可复盘的数据痕迹。
3. **投研证据链引擎**：不只看价格信号，还要求说明候选股与题材龙头的产业链/业务/事件关联，并检查行业龙头、情绪龙、机构持仓概率或研报覆盖等基本面线索。
4. **回测风控引擎**：所有“看多”都必须被交易成本、样本外验证、最大回撤、波动率、仓位上限和止损条件约束；风控结论优先于买入信号。
5. **研究生命周期引擎**：从 LLMQuant 风格工作流内化而来。一次分析必须能沉淀为观察池、买入 thesis、卖出条件、事件/宏观监控和研究健康检查，而不是看完即丢。
6. **Serenity chokepoint 研究门槛**：借鉴 `SevenBlues/serenity-chokepoint` 对公开 Serenity 框架的复现思路，把“AI/高景气产业链里不可绕开的瓶颈节点”作为深研过滤层。它不是直接交易信号，而是要求先验证供给集中、不可替代、需求/产能缺口、认证壁垒、低发现度和 red-team 反证，再进入本地 A 股题材、量价和风控流程。

## 已落地能力

- 数据获取：A 股 6 位代码，自动识别沪深市场，获取前复权日 K。
- 数据链路门禁：`analyze.py --health-check` 会批量检查哨兵股票历史行情和实时兜底；只要有一只失败，就先阻断完整分析/自动化复盘，避免空数据报告。
- pandas 特征工程：收益率、均线乖离、价格/成交量 Z-score、RSI、KDJ、MACD、ATR、波动率、回撤。
- 归一化处理：对需要尺度一致的模型使用 `StandardScaler`。
- 监督学习：决策树、随机森林、极端随机树、正则化逻辑回归、支持向量机、KNN 实例学习、MLP 神经网络。
- 集成算法：多个模型输出未来 N 日收益超过摩擦阈值的概率，过滤弱验证模型后做简单平均得到集成概率。
- 时间序列验证：使用带 `gap` 的 `TimeSeriesSplit`，避免随机打乱和跨期标签泄漏。
- 聚类分析：KMeans 识别最新样本属于哪类市场状态，并回看该簇历史胜率。
- 降维分析：PCA 判断特征压缩后的信息集中度。
- 马尔可夫链：把日收益分为下跌/震荡/上涨，估计下一日状态转移概率。
- 概率统计：Beta-Binomial 方式估计历史胜率后验均值和 90% 区间。
- 风控：最大回撤、20 日年化波动率、ATR、单标的研究仓位上限和止损参考；低分或极端回撤时明确不开新仓。
- 组合回测：`scripts/backtest.py` 支持多标的组合回测，使用前一交易日信号、下一交易日开盘成交，并显式计入佣金、最低佣金、卖出印花税、过户类费用和滑点，输出净值、回撤、胜率、交易次数和持仓。
- 题材扫描：`scripts/theme_scan.py` 读取 CSV 表格，输出 `theme_analyses`、`alpha_picks`、`position_plan` JSON；严格排除涨停股、资金净额非正、量化条件不达标和表外标的。
- 生命周期衔接：量化报告或题材扫描若产出候选股，应建议写入 `stock-research-lab` 的 watchlist/thesis，并至少包含一个 sell condition。

## 暂不默认使用的方向

- 重量级概率编程：PyMC/Stan 更适合组合级风控、层级因子模型或全市场横截面研究；单只股票样本太少，默认加入会显著增加依赖和过拟合风险。
- 深度时序网络：LSTM/Transformer 需要更大样本、特征库和严谨回测。当前只使用轻量 MLP 作为非线性参考。
- 全自动实盘下单：需要券商接口、交易成本、滑点、撤单、异常行情和权限控制，当前不包含。

## 推荐系统组成

1. 数据层：行情源适配、复权处理、交易日对齐、缓存和缺失值检查。
2. 特征层：技术指标、量价因子、风险因子、市场状态因子。
3. 模型层：监督学习概率、聚类状态、PCA、马尔可夫、贝叶斯统计。
4. 决策层：技术分、ML 分、风险分加权，输出建议。
5. 风控层：仓位上限、最大回撤、波动率、ATR 止损。
6. 回测层：未来应加入全市场批量选股、交易成本、样本外验证、组合回撤统计。
7. 报告层：解释每个信号来源，明确风险提示。

## 题材雷达规则

当用户提供涨停分析表、板块题材表、资金净额表，或要求“盯盘、题材轮动、潜力股筛选”时，优先走题材雷达：

1. **输入约束**：只使用用户给出的表格，不凭空补股票。字段可用中文或英文别名，包括股票代码、股票名称、概念名称、涨停分析、涨幅、资金净额、换手率、量比、概念强度值、流通市值、封单强度等。
2. **主线识别**：从已涨停且有涨停原因的股票中归因题材，按涨停个股数量、题材强度、资金净额排序，取前三大核心题材。
3. **强制过滤**：推荐股必须未涨停；主板涨幅低于 9.5%，创业板/科创板低于 19.5%；资金净额必须大于 0。
4. **量化过滤**：主板候选涨幅 5.0%-8.5%，创业板/科创板 6.0%-13.0%；资金净额大于 3000 万；换手率 5%-20%；若表中提供量比，则量比必须大于 1.8。
5. **证据链过滤**：候选股至少具备行业/细分龙头、历史情绪活跃、机构持仓概率、指数/大市值代表性或研报/调研覆盖等一种线索；证据不足时降级为备选。
6. **风险控制**：板块涨停数过多要提示高潮分化；换手接近上限或 20CM 标的接近筛选上沿时不得追高；封单强度弱时降低跟风股优先级。
7. **输出格式**：默认输出有效 JSON，包含 `analysis_date`、`most_promising_theme`、`theme_analyses`、`alpha_picks`、`risk_controls`。不要在 JSON 前后夹杂解释。

## 仓位模型

题材雷达输出必须包含 `position_plan`，不允许只给候选股；但所有仓位数字必须标明来源 profile，不能把本地假设包装成 GitHub 来源规则。

默认 profile 是 `llmquant-long-biased`，来源为 LLMQuant/skills 的 `llmquant-strategies/workflows/long-biased.md`。可直接复用的原文级组合规则是：

- 单票目标仓位：`3%-8%`
- 单票上限：`10%`
- 前五大持仓：`30%-50%` 组合权重
- 单行业上限：`30%`
- 目标净多暴露：`70%-95%`
- 目标总暴露：`100%-130%`
- 持仓数量：`15-30` 只集中多头
- 回撤触发：`-10%` 降低总暴露并重估；`-15%` 增加尾部保护；`-20%` 做完整组合复盘
- 流动性约束：每个持仓应能在 `<=20` 个交易日内、以低于 `20% ADV` 的速度退出

`theme_scan.py` 只把题材表候选映射到上述 `3%-8%` 区间，并输出 `profile_source/source_rules`。它无法凭一张题材表验证行业集中度、前五大集中度、ADV、真实组合净暴露或基本面 thesis，所以默认输出是研究仓位模板，不是自动下单指令。

另有三个 profile：

- `quant-paper`：来源为 LLMQuant/skills 的 `llmquant-strategies/workflows/quant.md`。在完成训练/验证/测试隔离、样本外回测、压力测试和 `3-6` 个月 paper trading 前，目标仓位为 `0%`，只观察记录。
- `serenity-chokepoint`：来源为 `SevenBlues/serenity-chokepoint` 的公开框架复现，内化为本地研究门槛而不是仓位规则。用它筛出“产业链瓶颈 + A 股题材承接”的候选，但在完成本地数据、交易成本、流动性、样本外 replay 和 `3-6` 个月 paper trading 前，目标仓位为 `0%`，只观察记录。
- `local-a-share-theme`：本地 A 股题材研究模板，不是 LLMQuant 来源。它保留旧的 `20%` 总研究暴露、`8%` 单票上限、`0.5%` 单笔风险预算、主板 `4.5%`/20CM `7.0%` 止损距离占位，仅用于用户明确选择本地模板或做回测实验时。

仓位计算原则：

1. 先识别 profile，并在 JSON 中写出 `profile_source`、`source_rules` 和 `profile_note`。
2. `llmquant-long-biased`：按候选分数、梯队、题材风险把候选映射到 `3%-8%`，高风险题材或风险折减后低于 `3%` 的候选只观察；止损距离不从 LLMQuant 硬编。
3. `quant-paper`：未完成回测和 paper trading 前全部 `0%`。
4. `serenity-chokepoint`：未完成 A 股本地验证前全部 `0%`；它只负责把候选升级为“值得深研/反证”的观察池。
5. `local-a-share-theme`：才使用本地止损距离和单笔风险预算公式 `目标仓位 <= 每笔风险预算 / 止损距离`。
6. 如果用户提供账户资金，例如 `--capital 100000`，输出目标金额；只有 profile 提供止损距离时才输出组合最大亏损金额。

## Serenity 综合策略用法

当用户要求把 Serenity 与既定量化策略合并时，按以下顺序执行：

1. **Serenity 深研过滤**：先问这只票是否处在不可绕开的供应链节点上，例如上游材料、设备、封装、光模块、连接器、工业软件、军工/半导体认证链等；没有供给集中、不可替代或认证壁垒证据的，只能作为普通题材票。
2. **反证清单**：明确替代技术、客户集中、扩产稀释、政策/出口管制、财务融资压力、订单兑现节奏、估值提前透支等风险。反证未过，不进入交易候选。
3. **A 股题材雷达**：再用 `theme_scan.py` 检查题材热度、资金净额、涨幅区间、换手、量比和风险级别，排除涨停、资金净额非正和量化条件不达标标的。
4. **量价确认**：对入围票用 `analyze.py` 做日线趋势、ML 概率、聚类/马尔可夫/贝叶斯状态和风险韧性诊断。
5. **仓位门槛**：默认使用 `--strategy-profile serenity-chokepoint` 时只输出观察计划；只有完成本地 A 股 replay、交易成本建模、流动性检查、样本外验证和纸面交易后，才允许把它升级到可试错仓位 profile。

## 使用方式

```bash
python scripts/analyze.py --health-check
python scripts/analyze.py --health-check --health-stocks 600519,000001,300750
python scripts/analyze.py --stock 600519 --days 120 --data-check
python scripts/analyze.py --stock 600519 --days 360
python scripts/analyze.py --stock 宁德时代 --days 720 --horizon 10
python scripts/analyze.py --stock 600519 --source premium
python scripts/analyze.py --stock 600519 --source push
python scripts/analyze.py --stock 600519 --source pull
python scripts/analyze.py --stock 600519 --source tushare
python scripts/analyze.py --stock 000001 --source tencent
python scripts/analyze.py --stock 600519 --source eastmoney
python scripts/analyze.py --stock 600519 --source stooq
python scripts/backtest.py --stocks 000001,000858,600000,300750,600519 --days 360 --initial-cash 1000000 --source auto
python scripts/backtest.py --stocks 000001,000858,600000,300750,600519 --days 720 --entry-score 58 --exit-score 45 --max-total-exposure-pct 80 --fee-bps 3 --min-commission 5 --tax-bps 5 --transfer-bps 0.1 --slippage-bps 5 --output-dir ../trading-journal/backtests/2026-06-07
python scripts/theme_scan.py --csv 今日涨停分析.csv --date 2026-05-31
python scripts/theme_scan.py --csv 今日涨停分析.csv --capital 100000 --strategy-profile llmquant-long-biased
python scripts/theme_scan.py --csv 今日涨停分析.csv --capital 100000 --strategy-profile local-a-share-theme --max-total-pct 20 --risk-budget-pct 0.5
python scripts/theme_scan.py --csv 今日涨停分析.csv --strategy-profile quant-paper
python scripts/theme_scan.py --csv 今日涨停分析.csv --strategy-profile serenity-chokepoint
```

参数：

- `--stock` / `-s`：A 股 6 位代码，或内置名称如“贵州茅台”“宁德时代”。
- `--days` / `-d`：分析天数，默认 360，范围会自动限制在 80 到 1200。
- `--horizon`：机器学习预测未来 N 日方向，默认 5，范围 1 到 20。
- `--source`：`premium`、`push`、`pull`、`tushare`、`auto`、`tencent`、`eastmoney`、`stooq`。网页默认 `premium`，即推送缓存优先、Tushare Pro 次优先、腾讯/东方财富兜底。
- `--data-check`：只检查单只股票历史行情和实时行情兜底，不运行指标或机器学习。
- `--health-check`：批量检查 A 股数据链路健康度，适合自动化、发布前和完整分析前先跑；默认哨兵股票为 `600519,000001,300750`。
- `--health-stocks`：覆盖健康检查哨兵股票列表，使用英文或中文逗号分隔。
- `backtest.py --stocks`：组合回测股票池，使用英文或中文逗号分隔。
- `backtest.py --entry-score / --exit-score`：开仓和平仓评分阈值；默认 `58/45`。
- `backtest.py --fee-bps / --min-commission`：佣金费率和单笔最低佣金；默认 `3 bps`、最低 `5` 元。
- `backtest.py --tax-bps`：卖出印花税，默认 `5 bps`，只在卖出时收取。
- `backtest.py --transfer-bps`：过户/经手类费用占位，默认 `0.1 bps`。
- `backtest.py --slippage-bps`：买卖滑点，默认 `5 bps`；买入提高成交价，卖出降低成交价。
- `backtest.py --output-dir`：可选输出 `equity_curve.csv`、`trades.csv`、`positions.csv`，建议写入 `trading-journal/backtests/<日期>`。
- `theme_scan.py --csv`：读取涨停分析/题材/资金流 CSV，输出题材轮动和候选股 JSON。
- `theme_scan.py --capital`：账户资金规模；提供后输出每只候选的目标金额、止损距离和最大亏损金额。
- `theme_scan.py --strategy-profile`：仓位 profile，默认 `llmquant-long-biased`；可选 `local-a-share-theme`、`quant-paper` 或 `serenity-chokepoint`。
- `theme_scan.py --max-total-pct`：覆盖 profile 的组合总暴露上限；默认随 profile。
- `theme_scan.py --max-single-pct`：覆盖 profile 的单票仓位上限；默认随 profile。
- `theme_scan.py --risk-budget-pct`：覆盖 profile 的每笔止损风险预算；LLMQuant long-biased 默认不使用。

## 输出解读

- 综合评分：技术指标、机器学习 edge 概率和风险韧性加权后的 0-100 分。
- 交易建议：研究信号、偏积极观察、观望、减仓或回避、高风险回避。
- 机器学习分：未来 N 日收益超过默认摩擦阈值的概率，不等于收益率预测。
- 聚类/马尔可夫/贝叶斯：作为市场状态辅助解释，不单独触发买卖。
- 风控建议：优先级高于买入信号，最大回撤和波动率过高时自动降仓。
- 题材 JSON：`theme_analyses` 是前三核心题材，`alpha_picks` 是 1-3 只未涨停候选股，`position_plan` 是目标仓位/金额/止损/最大亏损；若为空，说明没有标的同时满足强制过滤和风控条件。`portfolio_controls.profile_source` 必须用来判断仓位数字是否来自 LLMQuant、quant paper-trading 门槛，还是本地假设。
- 后续动作：对进入观察的个股，优先用 `stock-research-lab` 写入 thesis、卖出条件和复查日期；没有退出条件的候选股不算完整研究结论。

## 依赖

```bash
pip install -r requirements.txt
```

核心依赖：`requests`、`pandas`、`numpy`、`pandas-datareader`、`scikit-learn`、`scipy`。

如果 `scikit-learn` 或 `scipy` 未安装，脚本会尽量退回到技术指标分析，但完整机器学习报告需要安装全部依赖。

## 风险提示

本 Skill 输出仅供量化研究和辅助决策，不构成投资建议。A 股存在涨跌停、停牌、流动性、政策冲击和数据源稳定性问题。进入实盘前必须补齐全市场回测、交易成本建模、样本外验证、组合级风控和人工复核。
