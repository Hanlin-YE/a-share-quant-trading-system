const form = document.querySelector("#query-form");
const sidebar = document.querySelector(".sidebar");
const stockInput = document.querySelector("#stock-input");
const daysInput = document.querySelector("#days-input");
const horizonInput = document.querySelector("#horizon-input");
const sourceInput = document.querySelector("#source-input");
const sourcePolicy = document.querySelector("#source-policy");
const sourcePremiumState = document.querySelector("#source-premium-state");
const sourceRefresh = document.querySelector("#source-refresh");
const sourceDetail = document.querySelector("#source-detail");
const dataOpsState = document.querySelector("#data-ops-state");
const pipelinePush = document.querySelector("#pipeline-push");
const pipelineTushare = document.querySelector("#pipeline-tushare");
const pipelineFallback = document.querySelector("#pipeline-fallback");
const opsRefresh = document.querySelector("#ops-refresh");
const opsProduction = document.querySelector("#ops-production");
const riskPreferenceInput = document.querySelector("#risk-preference");
const stylePreferenceInput = document.querySelector("#style-preference");
const drawdownPreferenceInput = document.querySelector("#drawdown-preference");
const positionPreferenceInput = document.querySelector("#position-preference");
const preferenceSummary = document.querySelector("#preference-summary");
const formStatus = document.querySelector("#form-status");
const analyzeButton = document.querySelector("#analyze-button");
const reportOutput = document.querySelector("#report-output");
const copyReportButton = document.querySelector("#copy-report");
const progressBar = document.querySelector("#scroll-progress-bar");
const jumpBriefButton = document.querySelector("#jump-brief");
const scrollPrevButton = document.querySelector("#scroll-prev");
const scrollNextButton = document.querySelector("#scroll-next");
const helpDialog = document.querySelector("#help-dialog");
const helpTitle = document.querySelector("#help-title");
const helpBody = document.querySelector("#help-body");
const helpCloseButton = document.querySelector("#help-close");
const helpButtons = Array.from(document.querySelectorAll("[data-help]"));
const strategyButtons = Array.from(document.querySelectorAll("[data-strategy]"));
const navLinks = Array.from(document.querySelectorAll(".nav a"));
const scrollTargets = ["consult", "data-ops", "brief", "methodology", "evidence", "risk", "report"]
  .map((id) => document.getElementById(id))
  .filter(Boolean);
const revealSections = Array.from(document.querySelectorAll(".scroll-section"));
const apiBase =
  window.location.protocol === "file:" ? "http://127.0.0.1:8765" : window.location.origin;

const helpContent = {
  "final-score": {
    title: "综合评分与权重",
    body: [
      "综合评分是研究优先级分数，不是收益率预测，也不是买卖指令。",
      "机器学习可用时：综合评分 = 技术面质量 × 50% + 模型 Edge × 35% + 风险韧性 × 15%。",
      "机器学习不可用时：综合评分 = 技术面质量 × 75% + 风险韧性 × 25%，不会用空模型硬凑结论。",
      "如果风险韧性低于 25，最终建议会直接降为“高风险观察 / 不开新仓”，即风险门禁优先于分数。",
    ],
  },
  "current-view": {
    title: "Current View 与建议阈值",
    body: [
      "Current View 是当前研究结论的简写，例如观望、偏积极观察、减仓或回避。",
      "建议阈值：≥72 为强研究信号；58-72 为偏积极观察；45-58 为观望；32-45 为减仓或回避；<32 为高风险回避。",
      "风险韧性低于 25 时，即使综合评分较高，也优先输出高风险观察。",
      "这个字段是咨询摘要，用于快速判断下一步动作，不代表自动交易指令。",
    ],
  },
  technical: {
    title: "技术面质量：内部计分",
    body: [
      "技术面质量从 50 分基准开始，最后限制在 0-100 分。",
      "均线结构：MA5>MA10、MA10>MA20、MA20>MA60 每项 +10 分，三组均线合计后再扣 15 分作为趋势门槛。",
      "RSI：低于 30 视为短线超卖 +12；高于 70 视为短线超买 -12；中性区只记录不加分。",
      "KDJ-J：低于 20 +10；高于 80 -10。MACD 柱为正 +8，为负 -4。量比大于 1.5 +6，小于 0.5 -4。",
    ],
  },
  "model-edge": {
    title: "模型 Edge：机器学习权重",
    body: [
      "模型 Edge 是机器学习层对未来 N 日收益超过 0.30% 摩擦阈值的概率评分，乘以 100 后进入综合评分。",
      "模型可用时，它在综合评分中的权重是 35%；模型不可用时权重为 0，并自动退回技术 75% + 风险 25%。",
      "模型候选包括逻辑回归、决策树、随机森林、极端随机树、SVM、KNN 和 MLP，使用时间序列交叉验证和预测窗口 gap。",
      "样本不足、最新特征缺失或验证质量不足时，页面会显示未启用，避免把低可信模型包装成结论。",
    ],
  },
  "risk-resilience": {
    title: "风险韧性：扣分规则",
    body: [
      "风险韧性从 100 分开始扣分，最后限制在 0-100 分。",
      "最大回撤扣分：min(最大回撤% × 1.4, 45)。20 日年化波动扣分：min(年化波动 × 55, 30)。ATR 压力扣分：min(ATR/收盘价 × 500, 20)。",
      "机器学习可用时风险权重为 15%；模型不可用时风险权重为 25%。这让缺少模型证据时更重视风控。",
      "如果风险韧性低于 25，建议会被强制降级为高风险观察 / 不开新仓。",
    ],
  },
  execution: {
    title: "操作分层与仓位边界",
    body: [
      "操作分层把研究结论拆成观察、试错和回避三个动作层级。",
      "综合评分低于 45 或最大回撤大于 35% 时，单标的仓位建议为 0%，仅保留观察。",
      "45-58 分通常等待评分和风险状态改善；58-72 分研究仓位上限约 12%；≥72 分基础上限约 20%。",
      "若最大回撤超过 20%，仓位上限减半；若 20 日年化波动超过 45%，仓位上限再乘 0.75。",
      "这里的仓位边界是研究模板，不是自动下单策略。",
    ],
  },
  "core-indicators": {
    title: "核心指标快照",
    body: [
      "核心指标快照只展示报告原文中解析到的技术与风险数据，不使用装饰性推导图。",
      "均线结构用于判断趋势排列；MA5>MA10>MA20>MA60 代表更强的多头一致性，反向排列代表趋势压力。",
      "RSI 与 KDJ-J 用于识别短线超买或超卖；RSI<30 加分，RSI>70 扣分，KDJ-J<20 加分，KDJ-J>80 扣分。",
      "MACD 柱用于判断动能方向；柱值为正加分，为负扣分。量比用于判断近期成交活跃度。",
      "20 日年化波动率、ATR/收盘价和最大回撤进入风险韧性扣分，风控低于门槛会覆盖积极信号。",
    ],
  },
};

async function loadSourceCatalog() {
  try {
    const response = await fetch(`${apiBase}/api/sources`);
    if (!response.ok) return;
    const catalog = await response.json();
    const push = (catalog.sources || []).find((source) => source.id === "push");
    const tushare = (catalog.sources || []).find((source) => source.id === "tushare");
    const premium = (catalog.sources || []).find((source) => source.id === "premium");
    const fallbackSources = (catalog.sources || []).filter((source) => source.tier === "fallback" && source.enabled);
    sourcePolicy.textContent = catalog.policy || "专业源优先 / 多源回退";
    sourcePremiumState.textContent = push?.enabled ? "推送已启用" : "推送未配置";
    sourcePremiumState.className = push?.enabled ? "source-ok" : "source-warn";
    sourceRefresh.textContent = premium?.refresh || "交易日日频";
    sourceDetail.textContent = `默认链路：${premium?.refresh || "供应商推送缓存优先；未命中时自动拉取"}。${tushare?.enabled ? "Tushare Pro 已可用" : "Tushare Pro 未配置"}；公开源保留 ${fallbackSources.length || 0} 条兜底。`;
    dataOpsState.textContent = push?.enabled || tushare?.enabled ? "生产链路可用" : "演示链路可用";
    dataOpsState.className = `pill ${push?.enabled || tushare?.enabled ? "good" : "warn"}`;
    pipelinePush.textContent = push?.enabled ? "Webhook 已受密钥保护并可接收推送" : "未配置 DATA_WEBHOOK_SECRET，暂不接收外部推送";
    pipelineTushare.textContent = tushare?.enabled ? "Tushare Token 已配置，可作为授权数据源" : "未配置 TUSHARE_TOKEN，暂由公开源兜底";
    pipelineFallback.textContent = fallbackSources.length
      ? `${fallbackSources.map((source) => source.name).join(" / ")} 可用`
      : "暂无可用公开兜底源";
    opsRefresh.textContent = premium?.refresh || "Webhook 推送 / 定时刷新";
    opsProduction.textContent = push?.enabled || tushare?.enabled ? "已具备生产级接入基础" : "需配置供应商密钥后进入生产模式";
  } catch {
    sourcePolicy.textContent = "数据源状态待确认";
    sourcePremiumState.textContent = "检测失败";
    sourcePremiumState.className = "source-warn";
    sourceRefresh.textContent = "请查看后端日志";
    sourceDetail.textContent = "未能读取 /api/sources，请确认后端服务是否在线。";
    dataOpsState.textContent = "链路检测失败";
    dataOpsState.className = "pill bad";
    pipelinePush.textContent = "检测失败";
    pipelineTushare.textContent = "检测失败";
    pipelineFallback.textContent = "检测失败";
    opsRefresh.textContent = "请查看后端日志";
    opsProduction.textContent = "状态未知";
  }
}

const fields = {
  statusStock: document.querySelector("#status-stock"),
  statusState: document.querySelector("#status-state"),
  statusRange: document.querySelector("#status-range"),
  scoreTitle: document.querySelector("#score-title"),
  scorePill: document.querySelector("#score-pill"),
  suggestion: document.querySelector("#suggestion-text"),
  priceLine: document.querySelector("#price-line"),
  technicalScore: document.querySelector("#technical-score"),
  mlScore: document.querySelector("#ml-score"),
  riskScore: document.querySelector("#risk-score"),
  technicalMeter: document.querySelector("#technical-meter"),
  mlMeter: document.querySelector("#ml-meter"),
  riskMeter: document.querySelector("#risk-meter"),
  laneWatch: document.querySelector("#lane-watch"),
  laneTrial: document.querySelector("#lane-trial"),
  laneAvoid: document.querySelector("#lane-avoid"),
  strategyKicker: document.querySelector("#strategy-kicker"),
  strategyTitle: document.querySelector("#strategy-title"),
  strategyCondition: document.querySelector("#strategy-condition"),
  strategyEntry: document.querySelector("#strategy-entry"),
  strategyPosition: document.querySelector("#strategy-position"),
  strategyRisk: document.querySelector("#strategy-risk"),
  signalsList: document.querySelector("#signals-list"),
  riskList: document.querySelector("#risk-list"),
  indicatorTableBody: document.querySelector("#indicator-table-body"),
  matrixState: document.querySelector("#matrix-state"),
  matrixSecurity: document.querySelector("#matrix-security"),
  matrixSource: document.querySelector("#matrix-source"),
  matrixSample: document.querySelector("#matrix-sample"),
  matrixDays: document.querySelector("#matrix-days"),
  matrixPrice: document.querySelector("#matrix-price"),
  matrixChange: document.querySelector("#matrix-change"),
  matrixFinal: document.querySelector("#matrix-final"),
  matrixAdvice: document.querySelector("#matrix-advice"),
  matrixTechnical: document.querySelector("#matrix-technical"),
  matrixTrend: document.querySelector("#matrix-trend"),
  matrixModel: document.querySelector("#matrix-model"),
  matrixModelNote: document.querySelector("#matrix-model-note"),
  matrixRisk: document.querySelector("#matrix-risk"),
  matrixRiskNote: document.querySelector("#matrix-risk-note"),
  matrixGate: document.querySelector("#matrix-gate"),
  matrixGateNote: document.querySelector("#matrix-gate-note"),
  matrixRsi: document.querySelector("#matrix-rsi"),
  matrixKdj: document.querySelector("#matrix-kdj"),
  matrixMacd: document.querySelector("#matrix-macd"),
  matrixVol: document.querySelector("#matrix-vol"),
  matrixAtr: document.querySelector("#matrix-atr"),
  matrixDd: document.querySelector("#matrix-dd"),
  policyStatus: document.querySelector("#policy-status"),
  policyProfile: document.querySelector("#policy-profile"),
  policyLimits: document.querySelector("#policy-limits"),
  policyAction: document.querySelector("#policy-action"),
  policyReason: document.querySelector("#policy-reason"),
  policyPosition: document.querySelector("#policy-position"),
  policyPositionNote: document.querySelector("#policy-position-note"),
  policyTrigger: document.querySelector("#policy-trigger"),
  policyTriggerNote: document.querySelector("#policy-trigger-note"),
};

let lastPayload = null;
let selectedStrategy = "observation";

const riskPreferenceLabels = {
  conservative: "稳健型",
  balanced: "平衡型",
  aggressive: "积极型",
};

const stylePreferenceLabels = {
  short: "短线",
  swing: "波段",
  position: "中线",
};

const preferenceRules = {
  conservative: { scoreOffset: 8, riskFloor: 55, positionFactor: 0.55 },
  balanced: { scoreOffset: 0, riskFloor: 42, positionFactor: 0.78 },
  aggressive: { scoreOffset: -6, riskFloor: 32, positionFactor: 1 },
};

const styleRules = {
  short: { trigger: "优先看 RSI/KDJ 修复与 MACD 柱连续转强", positionFactor: 0.75 },
  swing: { trigger: "等待站回 20 日均线，且模型 Edge 不低于 50%", positionFactor: 0.9 },
  position: { trigger: "要求 20/60 日均线改善，回撤压力继续收敛", positionFactor: 0.65 },
};

function formatScore(score) {
  return Number.isFinite(score) ? score.toFixed(1) : "-";
}

function isMetric(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function formatMetric(value, digits = 2, suffix = "") {
  return isMetric(value) ? `${value.toFixed(digits)}${suffix}` : "N/A";
}

function setList(target, items) {
  target.innerHTML = "";
  const normalized = items && items.length ? items : ["暂无可展示条目。"];
  normalized.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    target.appendChild(li);
  });
}

function classifyScore(score) {
  if (!Number.isFinite(score)) return { text: "等待分析", className: "" };
  if (score >= 72) return { text: "强研究信号", className: "good" };
  if (score >= 58) return { text: "积极观察", className: "good" };
  if (score >= 45) return { text: "保持观望", className: "warn" };
  return { text: "风险优先", className: "bad" };
}

function assessMovingAverage(metrics) {
  const values = [metrics.ma_5, metrics.ma_10, metrics.ma_20, metrics.ma_60];
  if (!values.every(isMetric)) return "N/A：样本不足或报告未返回完整均线";
  if (metrics.ma_5 > metrics.ma_10 && metrics.ma_10 > metrics.ma_20 && metrics.ma_20 > metrics.ma_60) {
    return "多头排列；MA 组每项满足条件 +10，合计后扣 15 趋势门槛";
  }
  if (metrics.ma_5 < metrics.ma_10 && metrics.ma_10 < metrics.ma_20 && metrics.ma_20 < metrics.ma_60) {
    return "空头排列；均线结构不贡献多头加分";
  }
  return "均线交错；趋势一致性不足，按逐组关系计分";
}

function shortTrend(metrics) {
  const values = [metrics.ma_5, metrics.ma_10, metrics.ma_20, metrics.ma_60];
  if (!values.every(isMetric)) return "均线 N/A";
  if (metrics.ma_5 > metrics.ma_10 && metrics.ma_10 > metrics.ma_20 && metrics.ma_20 > metrics.ma_60) {
    return "MA 多头排列";
  }
  if (metrics.ma_5 < metrics.ma_10 && metrics.ma_10 < metrics.ma_20 && metrics.ma_20 < metrics.ma_60) {
    return "MA 空头排列";
  }
  return "MA 交错";
}

function assessRsi(value) {
  if (!isMetric(value)) return "N/A：报告未返回 RSI";
  if (value < 30) return "短线超卖；技术分 +12";
  if (value > 70) return "短线超买；技术分 -12";
  return "中性区；记录状态，不加减分";
}

function assessKdj(value) {
  if (!isMetric(value)) return "N/A：报告未返回 KDJ-J";
  if (value < 20) return "偏超卖；技术分 +10";
  if (value > 80) return "偏超买；技术分 -10";
  return "中性区；记录状态，不加减分";
}

function assessMacd(value) {
  if (!isMetric(value)) return "N/A：报告未返回 MACD 柱";
  return value > 0 ? "多头动能占优；技术分 +8" : "动能偏弱；技术分 -4";
}

function assessVolumeRatio(value) {
  if (!isMetric(value)) return "N/A：报告未返回量比";
  if (value > 1.5) return "近期放量；技术分 +6";
  if (value < 0.5) return "交投收缩；技术分 -4";
  return "成交中性；记录状态，不加减分";
}

function assessVolatility(value) {
  if (!isMetric(value)) return "N/A：报告未返回波动率";
  return `进入风险韧性扣分：min(${value.toFixed(2)}% × 55, 30)`;
}

function assessAtr(value) {
  if (!isMetric(value)) return "N/A：报告未返回 ATR";
  return `进入风险韧性扣分：min(${value.toFixed(2)}% × 500, 20)`;
}

function assessDrawdown(value) {
  if (!isMetric(value)) return "N/A：报告未返回最大回撤";
  const gate = value > 20 ? "超过 20%，仓位上限会被降低" : "未超过 20% 观察线";
  return `${gate}；扣分 min(${value.toFixed(2)}% × 1.4, 45)`;
}

function setIndicatorRows(metrics = {}) {
  const maValue =
    [metrics.ma_5, metrics.ma_10, metrics.ma_20, metrics.ma_60].every(isMetric)
      ? `MA5 ${formatMetric(metrics.ma_5)} / MA10 ${formatMetric(metrics.ma_10)} / MA20 ${formatMetric(
          metrics.ma_20,
        )} / MA60 ${formatMetric(metrics.ma_60)}`
      : "N/A";
  const rows = [
    ["均线结构", maValue, assessMovingAverage(metrics)],
    ["RSI(14)", formatMetric(metrics.rsi_14), assessRsi(metrics.rsi_14)],
    ["KDJ-J", formatMetric(metrics.kdj_j), assessKdj(metrics.kdj_j)],
    ["MACD 柱", formatMetric(metrics.macd_hist, 4), assessMacd(metrics.macd_hist)],
    ["量比", formatMetric(metrics.volume_ratio_5), assessVolumeRatio(metrics.volume_ratio_5)],
    ["20 日年化波动率", formatMetric(metrics.volatility_20_pct, 2, "%"), assessVolatility(metrics.volatility_20_pct)],
    ["ATR(14)/收盘价", formatMetric(metrics.atr_pct_14, 2, "%"), assessAtr(metrics.atr_pct_14)],
    ["最大回撤", formatMetric(metrics.max_drawdown_pct, 2, "%"), assessDrawdown(metrics.max_drawdown_pct)],
  ];

  fields.indicatorTableBody.innerHTML = "";
  rows.forEach(([label, value, note]) => {
    const row = document.createElement("tr");
    const header = document.createElement("th");
    const valueCell = document.createElement("td");
    const noteCell = document.createElement("td");
    header.scope = "row";
    header.textContent = label;
    valueCell.textContent = value;
    noteCell.textContent = note;
    row.append(header, valueCell, noteCell);
    fields.indicatorTableBody.appendChild(row);
  });
}

function firstMatched(items, pattern, fallback = "N/A") {
  const found = (items || []).find((item) => pattern.test(item));
  return found || fallback;
}

function getPreferences() {
  return {
    risk: riskPreferenceInput.value,
    style: stylePreferenceInput.value,
    drawdownLimit: Number(drawdownPreferenceInput.value),
    positionLimit: Number(positionPreferenceInput.value),
  };
}

function updatePreferenceSummary() {
  const preferences = getPreferences();
  preferenceSummary.textContent = `${riskPreferenceLabels[preferences.risk]} / ${stylePreferenceLabels[preferences.style]} / 回撤 ${preferences.drawdownLimit}% / 仓位 ${preferences.positionLimit}%`;
  updatePersonalizedPolicy(lastPayload);
  updateStrategyDetail();
}

function classifyPolicy(payload, preferences) {
  if (!payload || !payload.ok) {
    return {
      status: { text: "等待分析", className: "" },
      action: "等待分析",
      reason: "先生成报告，再按交易偏好重算执行边界。",
      position: "-",
      positionNote: "仓位由综合评分、风险韧性、最大回撤和用户上限共同约束。",
      trigger: "-",
      triggerNote: "等待核心指标。",
    };
  }

  const scores = payload.scores || {};
  const metrics = payload.technical_metrics || {};
  const riskRule = preferenceRules[preferences.risk];
  const styleRule = styleRules[preferences.style];
  const finalScore = Number.isFinite(scores.final) ? scores.final : 0;
  const riskScore = Number.isFinite(scores.risk) ? scores.risk : 0;
  const maxDrawdown = Number.isFinite(metrics.max_drawdown_pct) ? metrics.max_drawdown_pct : 100;
  const personalizedScore = finalScore - riskRule.scoreOffset;
  const blockedByDrawdown = maxDrawdown > preferences.drawdownLimit;
  const blockedByRisk = riskScore < riskRule.riskFloor;
  const canTrial = personalizedScore >= 58 && !blockedByRisk && !blockedByDrawdown;
  const canWatch = personalizedScore >= 45 && !blockedByRisk;
  let action = "仅观察";
  let className = "warn";
  let reason = "偏好门槛下尚不满足试仓条件。";

  if (canTrial) {
    action = preferences.risk === "aggressive" ? "允许进攻试仓" : "允许小仓验证";
    className = "good";
    reason = "模型评分、风险韧性和用户回撤容忍均通过偏好门槛。";
  } else if (blockedByDrawdown || blockedByRisk) {
    action = "不适合当前偏好";
    className = "bad";
    reason = blockedByDrawdown
      ? `最大回撤 ${maxDrawdown.toFixed(2)}% 超过你的 ${preferences.drawdownLimit}% 容忍线。`
      : `风险韧性 ${formatScore(riskScore)} 低于 ${riskPreferenceLabels[preferences.risk]} 门槛 ${riskRule.riskFloor}。`;
  } else if (canWatch) {
    action = "观察等待确认";
    className = "warn";
    reason = "评分接近门槛，但仍需要价格或模型信号进一步确认。";
  }

  const basePosition = canTrial ? Math.max(1, Math.round(((personalizedScore - 50) / 50) * preferences.positionLimit)) : 0;
  const adjustedPosition = Math.min(
    preferences.positionLimit,
    Math.max(0, Math.round(basePosition * riskRule.positionFactor * styleRule.positionFactor)),
  );

  return {
    status: { text: action, className },
    action,
    reason,
    position: `${adjustedPosition}%`,
    positionNote:
      adjustedPosition > 0
        ? `不超过你的 ${preferences.positionLimit}% 单票上限；若回撤扩大，自动降至观察。`
        : `当前偏好下建议 0%，保留观察和复核。`,
    trigger: stylePreferenceLabels[preferences.style],
    triggerNote: styleRule.trigger,
  };
}

function updatePersonalizedPolicy(payload) {
  const preferences = getPreferences();
  const policy = classifyPolicy(payload, preferences);
  fields.policyStatus.textContent = policy.status.text;
  fields.policyStatus.className = `pill ${policy.status.className}`;
  fields.policyProfile.textContent = `${riskPreferenceLabels[preferences.risk]} / ${stylePreferenceLabels[preferences.style]}`;
  fields.policyLimits.textContent = `回撤容忍 ${preferences.drawdownLimit}%，单票上限 ${preferences.positionLimit}%`;
  fields.policyAction.textContent = policy.action;
  fields.policyReason.textContent = policy.reason;
  fields.policyPosition.textContent = policy.position;
  fields.policyPositionNote.textContent = policy.positionNote;
  fields.policyTrigger.textContent = policy.trigger;
  fields.policyTriggerNote.textContent = policy.triggerNote;
}

function strategyName(strategy) {
  return {
    observation: "观察池策略",
    trial: "试仓验证策略",
    avoid: "回避防守策略",
  }[strategy];
}

function buildStrategy(strategy, payload) {
  const preferences = getPreferences();
  const policy = classifyPolicy(payload, preferences);
  const metrics = payload?.technical_metrics || {};
  const scores = payload?.scores || {};
  const maxDd = formatMetric(metrics.max_drawdown_pct, 2, "%");
  const atr = formatMetric(metrics.atr_pct_14, 2, "%");
  const finalScore = formatScore(scores.final);
  const riskScore = formatScore(scores.risk);
  const position = policy.position || "0%";
  const trigger = styleRules[preferences.style].trigger;

  if (!payload || !payload.ok) {
    return {
      kicker: `${strategy[0].toUpperCase()}${strategy.slice(1)} Strategy`,
      title: strategyName(strategy),
      condition: "等待分析结果和交易偏好。",
      entry: "先生成报告，再给出策略条件。",
      position: "-",
      risk: "-",
    };
  }

  if (strategy === "observation") {
    return {
      kicker: "Observation Strategy",
      title: "观察池策略",
      condition: `综合 ${finalScore} / 风险 ${riskScore}；适合先跟踪，不急于执行。`,
      entry: trigger,
      position: "0%，只记录观察位和触发线",
      risk: `若 MaxDD 继续高于 ${preferences.drawdownLimit}% 或 ATR 高于 ${atr}，维持观察。`,
    };
  }

  if (strategy === "trial") {
    return {
      kicker: "Trial Strategy",
      title: "试仓验证策略",
      condition:
        policy.position === "0%"
          ? `当前偏好下未通过试仓门槛：${policy.reason}`
          : `偏好门槛通过，可用 ${riskPreferenceLabels[preferences.risk]} / ${stylePreferenceLabels[preferences.style]} 模式验证。`,
      entry: `触发：${trigger}；同时要求价格不再扩大 MaxDD ${maxDd}。`,
      position: `建议 ${position}，最高不超过用户单票上限 ${preferences.positionLimit}%。`,
      risk: `跌破 20 日均线且模型 Edge 低于 50% 时退出；ATR 当前 ${atr}。`,
    };
  }

  return {
    kicker: "Avoid Strategy",
    title: "回避防守策略",
    condition: `当风险韧性低于偏好门槛、MaxDD 超过 ${preferences.drawdownLimit}% 或综合分弱于 45 时启用。`,
    entry: "不做新仓；只保留复盘样本和后续再评估触发条件。",
    position: "0%",
    risk: `若已有持仓，优先降到用户上限以下；当前系统建议：${payload.suggestion || "N/A"}。`,
  };
}

function updateStrategyDetail() {
  const strategy = buildStrategy(selectedStrategy, lastPayload);
  fields.strategyKicker.textContent = strategy.kicker;
  fields.strategyTitle.textContent = strategy.title;
  fields.strategyCondition.textContent = strategy.condition;
  fields.strategyEntry.textContent = strategy.entry;
  fields.strategyPosition.textContent = strategy.position;
  fields.strategyRisk.textContent = strategy.risk;
  strategyButtons.forEach((button) => {
    const active = button.dataset.strategy === selectedStrategy;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function updateIntelMatrix(payload, scoreState) {
  const scores = payload.scores || {};
  const metrics = payload.technical_metrics || {};
  const dataRange = payload.data_range || {};
  const price = payload.price || {};
  const stockName = payload.stock_name ? `${payload.stock_code} ${payload.stock_name}` : payload.stock_code || "-";
  const range = dataRange.start && dataRange.end ? `${dataRange.start} / ${dataRange.end}` : "-";
  const riskControls = payload.risk_controls || [];
  const modelEvidence = payload.model_evidence || [];
  const maxDd = formatMetric(metrics.max_drawdown_pct, 2, "%");
  const atr = formatMetric(metrics.atr_pct_14, 2, "%");
  const volatility = formatMetric(metrics.volatility_20_pct, 2, "%");

  fields.matrixState.textContent = scoreState.text;
  fields.matrixState.className = `pill ${scoreState.className}`;
  fields.matrixSecurity.textContent = stockName;
  fields.matrixSource.textContent = payload.data_source || "数据源 N/A";
  if (payload.data_note) {
    fields.matrixSource.title = payload.data_note;
  }
  fields.matrixSample.textContent = range;
  fields.matrixDays.textContent = Number.isFinite(dataRange.trading_days) ? `${dataRange.trading_days} 个交易日` : "交易日 N/A";
  fields.matrixPrice.textContent = isMetric(price.close) ? price.close.toFixed(2) : "-";
  fields.matrixChange.textContent = isMetric(price.change_pct)
    ? `日变动 ${price.change_pct >= 0 ? "+" : ""}${price.change_pct.toFixed(2)}%`
    : "日变动 N/A";
  fields.matrixFinal.textContent = formatScore(scores.final);
  fields.matrixAdvice.textContent = payload.suggestion || "建议待生成";
  fields.matrixTechnical.textContent = formatScore(scores.technical);
  fields.matrixTrend.textContent = shortTrend(metrics);
  fields.matrixModel.textContent = formatScore(scores.machine_learning);
  fields.matrixModelNote.textContent = firstMatched(modelEvidence, /edge概率|未启用|退回技术指标/, "Edge N/A");
  fields.matrixRisk.textContent = formatScore(scores.risk);
  fields.matrixRiskNote.textContent = `MaxDD ${maxDd} / ATR ${atr}`;
  fields.matrixGate.textContent = firstMatched(riskControls, /仓位建议/, "待生成").replace(/^单标的/, "");
  fields.matrixGateNote.textContent = firstMatched(riskControls, /止损参考|最大回撤/, "风控线待生成");
  fields.matrixRsi.textContent = `RSI ${formatMetric(metrics.rsi_14)}`;
  fields.matrixKdj.textContent = `KDJ-J ${formatMetric(metrics.kdj_j)}`;
  fields.matrixMacd.textContent = `MACD ${formatMetric(metrics.macd_hist, 4)}`;
  fields.matrixVol.textContent = `20D Vol ${volatility}`;
  fields.matrixAtr.textContent = `ATR ${atr}`;
  fields.matrixDd.textContent = `MaxDD ${maxDd}`;
}

function scrollToSection(section) {
  if (!section) return;
  window.scrollTo({
    top: Math.max(0, sectionTop(section) - scrollOffset()),
    behavior: "smooth",
  });
}

function sectionTop(section) {
  return section.getBoundingClientRect().top + window.scrollY;
}

function scrollOffset() {
  if (window.matchMedia("(max-width: 760px)").matches) {
    return Math.min((sidebar?.offsetHeight || 0) + 16, window.innerHeight * 0.5);
  }
  if (window.matchMedia("(max-width: 1180px)").matches) {
    return (sidebar?.offsetHeight || 0) + 16;
  }
  return 16;
}

function currentSectionIndex() {
  const viewportMark = window.scrollY + scrollOffset() + 24;
  let activeIndex = 0;
  let activeTop = -Infinity;
  scrollTargets.forEach((section, index) => {
    const top = sectionTop(section);
    if (top - 24 <= viewportMark && top > activeTop) {
      activeIndex = index;
      activeTop = top;
    }
  });
  if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 6) {
    return scrollTargets.length - 1;
  }
  return activeIndex;
}

function updateScrollState() {
  const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
  const progress = maxScroll > 0 ? (window.scrollY / maxScroll) * 100 : 0;
  progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;

  const activeIndex = currentSectionIndex();
  const activeId = scrollTargets[activeIndex]?.id;
  navLinks.forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === `#${activeId}`);
  });
}

function setupRevealObserver() {
  revealSections.forEach((section) => {
    section.classList.add("reveal-ready");
  });

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
        }
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
  );

  revealSections.forEach((section) => observer.observe(section));
}

function openHelp(topic) {
  const content = helpContent[topic];
  if (!content) return;
  helpTitle.textContent = content.title;
  helpBody.innerHTML = "";
  const intro = document.createElement("p");
  intro.textContent = content.body[0];
  helpBody.appendChild(intro);
  if (content.body.length > 1) {
    const list = document.createElement("ul");
    content.body.slice(1).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      list.appendChild(li);
    });
    helpBody.appendChild(list);
  }
  if (typeof helpDialog.showModal === "function") {
    helpDialog.showModal();
  } else {
    helpDialog.setAttribute("open", "");
  }
}

function closeHelp() {
  if (typeof helpDialog.close === "function") {
    helpDialog.close();
  } else {
    helpDialog.removeAttribute("open");
  }
}

function updateDashboard(payload) {
  document.body.classList.remove("pre-analysis");
  document.body.classList.add("analysis-ready");
  document.querySelectorAll(".post-analysis-section").forEach((section) => {
    section.classList.add("in-view");
  });
  formStatus.textContent = "评估完成：目录、结论摘要、证据链、风控门禁和报告全文已展开。";
  lastPayload = payload;
  const scores = payload.scores || {};
  const finalScore = scores.final;
  const scoreState = classifyScore(finalScore);
  const stockName = payload.stock_name ? `${payload.stock_code} ${payload.stock_name}` : payload.stock_code;
  const dataRange = payload.data_range || {};
  const price = payload.price || {};

  fields.statusStock.textContent = stockName || "未知标的";
  fields.statusState.textContent = payload.suggestion || "分析完成";
  fields.statusRange.textContent = dataRange.start && dataRange.end ? `${dataRange.start} 至 ${dataRange.end}` : "-";
  updateIntelMatrix(payload, scoreState);
  fields.scoreTitle.textContent = `${formatScore(finalScore)} / 100`;
  fields.scorePill.textContent = scoreState.text;
  fields.scorePill.className = `pill ${scoreState.className}`;
  fields.suggestion.textContent = payload.suggestion || "暂无建议";
  if (Number.isFinite(price.close) && Number.isFinite(price.change_pct)) {
    fields.priceLine.textContent = `当前价格 ${price.close.toFixed(2)}，日变动 ${
      price.change_pct >= 0 ? "+" : ""
    }${price.change_pct.toFixed(2)}%。`;
  } else if (Number.isFinite(price.close)) {
    fields.priceLine.textContent = `当前价格 ${price.close.toFixed(2)}，涨跌幅未能解析。`;
  } else {
    fields.priceLine.textContent = "行情价格未能解析，请查看报告原文。";
  }

  fields.technicalScore.textContent = formatScore(scores.technical);
  fields.mlScore.textContent = formatScore(scores.machine_learning);
  fields.riskScore.textContent = formatScore(scores.risk);
  fields.technicalMeter.value = Number.isFinite(scores.technical) ? scores.technical : 0;
  fields.mlMeter.value = Number.isFinite(scores.machine_learning) ? scores.machine_learning : 0;
  fields.riskMeter.value = Number.isFinite(scores.risk) ? scores.risk : 0;

  fields.laneWatch.textContent = finalScore >= 45 ? "纳入观察" : "仅作样本";
  fields.laneTrial.textContent = finalScore >= 58 ? "小仓验证" : "等待确认";
  fields.laneAvoid.textContent = finalScore < 45 ? "优先回避" : "设风控线";

  setList(fields.signalsList, [...(payload.signals || []), ...(payload.model_evidence || []).slice(0, 3)]);
  setList(fields.riskList, payload.risk_controls || []);
  reportOutput.textContent = payload.report || "无报告内容。";
  setIndicatorRows(payload.technical_metrics || {});
  updatePersonalizedPolicy(payload);
  updateStrategyDetail();
  updateScrollState();
}

function setError(message, report) {
  lastPayload = null;
  document.body.classList.add("pre-analysis");
  document.body.classList.remove("analysis-ready");
  formStatus.textContent = "暂未生成报告，请检查股票代码、数据源或分析参数后重新提交。";
  fields.statusState.textContent = "分析失败";
  fields.scorePill.textContent = "需检查";
  fields.scorePill.className = "pill bad";
  fields.suggestion.textContent = "未能生成咨询结论";
  fields.priceLine.textContent = message;
  updateIntelMatrix(
    {
      stock_code: stockInput.value.trim() || "-",
      suggestion: "分析失败",
      data_source: "连接失败",
      scores: {},
      price: {},
      data_range: {},
      technical_metrics: {},
      risk_controls: [message],
      model_evidence: [],
    },
    { text: "需检查", className: "bad" },
  );
  setList(fields.signalsList, [message]);
  setList(fields.riskList, ["请确认股票代码、网络行情源与数据源设置。"]);
  setIndicatorRows({});
  updatePersonalizedPolicy(null);
  updateStrategyDetail();
  reportOutput.textContent = report || message;
}

async function runAnalysis() {
  const stock = stockInput.value.trim();
  if (!/^\d{6}$/.test(stock)) {
    setError("请输入 6 位 A 股代码，例如 600519、000001、300750。");
    stockInput.focus();
    return;
  }

  const params = new URLSearchParams({
    stock,
    days: daysInput.value,
    horizon: horizonInput.value,
    source: sourceInput.value,
  });

  analyzeButton.disabled = true;
  analyzeButton.textContent = "分析中";
  formStatus.textContent = "正在连接行情源、计算技术指标并按你的偏好生成总报告。";
  fields.statusStock.textContent = stock;
  fields.statusState.textContent = "连接行情源与量化模型";

  try {
    const response = await fetch(`${apiBase}/api/analyze?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      setError(payload.error || "分析失败。", payload.report);
      return;
    }
    updateDashboard(payload);
    window.setTimeout(() => scrollToSection(document.querySelector("#brief")), 180);
  } catch (error) {
    setError(`请求失败：${error.message}`);
  } finally {
    analyzeButton.disabled = false;
    analyzeButton.textContent = "生成咨询";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runAnalysis();
});

jumpBriefButton.addEventListener("click", () => {
  scrollToSection(document.querySelector("#brief"));
});

scrollPrevButton.addEventListener("click", () => {
  const index = currentSectionIndex();
  scrollToSection(scrollTargets[Math.max(0, index - 1)]);
});

scrollNextButton.addEventListener("click", () => {
  const index = currentSectionIndex();
  scrollToSection(scrollTargets[Math.min(scrollTargets.length - 1, index + 1)]);
});

navLinks.forEach((link) => {
  link.addEventListener("click", (event) => {
    const id = link.getAttribute("href")?.slice(1);
    const target = id ? document.getElementById(id) : null;
    if (target) {
      event.preventDefault();
      navLinks.forEach((item) => item.classList.toggle("active", item === link));
      scrollToSection(target);
    }
  });
});

window.addEventListener("scroll", updateScrollState, { passive: true });
window.addEventListener("resize", updateScrollState);

helpButtons.forEach((button) => {
  button.addEventListener("click", () => {
    openHelp(button.dataset.help);
  });
});

helpCloseButton.addEventListener("click", closeHelp);

helpDialog.addEventListener("click", (event) => {
  if (event.target === helpDialog) {
    closeHelp();
  }
});

strategyButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedStrategy = button.dataset.strategy;
    updateStrategyDetail();
  });
});

copyReportButton.addEventListener("click", async () => {
  const text = reportOutput.textContent;
  try {
    await navigator.clipboard.writeText(text);
    copyReportButton.textContent = "已复制";
    setTimeout(() => {
      copyReportButton.textContent = "复制报告";
    }, 1200);
  } catch {
    copyReportButton.textContent = "复制失败";
    setTimeout(() => {
      copyReportButton.textContent = "复制报告";
    }, 1200);
  }
});

[riskPreferenceInput, stylePreferenceInput, drawdownPreferenceInput, positionPreferenceInput].forEach((input) => {
  input.addEventListener("input", updatePreferenceSummary);
  input.addEventListener("change", updatePreferenceSummary);
});

setIndicatorRows({});
updatePreferenceSummary();
updateStrategyDetail();
setupRevealObserver();
updateScrollState();
loadSourceCatalog();
