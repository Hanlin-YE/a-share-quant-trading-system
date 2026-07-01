# 项目长期记忆

## 项目：龙头跟随交易系统（Shenzhen intern trail）

### 核心策略文档
- 《龙头跟随核心概要V1.0》：四层筛选 + 分4仓滚动 + 三层股池TTL4天
- 第一层 新闻/热搜扫描（金十/Wind/官媒+百度/谷歌/今日头条热搜前10）→ DS分析热点
- 第二层 主力埋伏（近5/10/20日主力资金+业务占比>15%）
- 第三层 量能+大单（成交额>两市1/7500、大单占比17-50%、4/11/117参考、盘整否决、≥2只参考人气榜）
- 第四层 买点（涨幅>7.5%打板、DIF背离、A/B突破前高；龙一封板后跟龙二/龙三）
- 卖点：次日不妙板卖、龙一躺全躺止损、破趋势线卖

### 数据源（实测可用）
- 东方财富 clist：用 `push2delay.eastmoney.com`（push2 间歇502，push2delay稳定200）
- 东方财富 kline：`push2his.eastmoney.com` 稳定
- 东方财富 fflow：`push2his.eastmoney.com/fflow` 不稳定（Empty reply），失败降级用当日f62
- 腾讯 qt：`qt.gtimg.cn` 稳定，用于两市成交额（gbk编码）
- 百度热搜：`top.baidu.com/api/board` JSON 可用
- 今日头条热搜：`toutiao.com/hot-event/hot-board` JSON 可用
- DeepSeek：`.env` 有 API key，用于新闻分析

### 关键技术约定
- 网络请求统一用 subprocess curl（urllib 在代理环境被 502 拒绝）
- hot_terms 匹配用子串包含（DeepSeek"机器人"匹配eastmoney"机器人概念"），非精确交集
- hot_terms_from_deepseek 要把复合主题按 /+、 拆分
- scan 性能：候选限15只 + ThreadPoolExecutor 并发8 + fflow降级，目标<3分钟

### 文件结构
- src/models.py：MarketStock(含V1.0扩展字段) + PoolEntry/Position/SellSignal
- src/pipeline.py：四层筛选 + DEFAULT_THRESHOLDS(对齐V1.0)
- src/hotspot.py：纯Python热点提取引擎（关键词频次+涨停聚类+交叉验证，LLM可选增强）
- src/pools.py：三层股池 hot/screened/trade + TTL4天
- src/portfolio.py：分4仓 + 卖点信号
- src/ports.py：NewsSource/MarketSource/LLMAnalyzer Protocol
- src/adapters/eastmoney.py：行情(clist/kline/fflow) + 两市总量
- src/adapters/news.py：百度/头条/谷歌/官媒/金十/Wind
- src/adapters/deepseek.py：LLM分析
- src/cli.py：scan/watch/run/doctor 命令
- src/report.py：HTML报告
- tests/：11个测试全通过
