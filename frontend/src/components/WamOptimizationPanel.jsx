import { useEffect, useMemo, useRef, useState } from 'react'
import { postWamOptimize } from '../api'
import './wam-optimization.css'

const RISK_PROFILES = {
  balanced: {
    label: '均衡',
    weights: { flood: 8, severe: 18, uncertainty: 2, energy: 0.25, mobilization: 0.2 },
  },
  conservative: {
    label: '生命安全优先',
    weights: { flood: 10, severe: 26, uncertainty: 3, energy: 0.12, mobilization: 0.12 },
  },
  efficient: {
    label: '能耗约束',
    weights: { flood: 7, severe: 17, uncertainty: 2, energy: 0.55, mobilization: 0.45 },
  },
}

const SEARCH_BUDGETS = {
  quick: { label: '快速搜索', population: 16, iterations: 2 },
  standard: { label: '标准搜索', population: 32, iterations: 3 },
  robust: { label: '稳健搜索', population: 64, iterations: 5 },
}

const LOOP_STAGES = [
  { id: 'observe', index: '01', title: '数据接入', tech: '当前 API / 缓存 · 目标 MQTT / Kafka', desc: '已接天气、GIS 与水位；SCADA、雷达、交通和工单待接' },
  { id: 'belief', index: '02', title: '信念状态', tech: '当前 Spin-up + 局地 EnSRF', desc: '十区初始水深集合、降雨潮位、泵效参数与预测方差' },
  { id: 'world', index: '03', title: '世界推演', tech: '当前守恒图模型 · 残差待训练', desc: '同源集合模拟、反事实与水量账本' },
  { id: 'search', index: '04', title: '动作搜索', tech: '当前稳健 CEM · MPC / MILP 演进', desc: '搜索十区排水控制；离散资源尚未接入' },
  { id: 'shield', index: '05', title: '安全投影', tech: '当前边界 / 预算 / 无恶化护栏', desc: '确定性投影后用成对集合再次验证' },
  { id: 'approve', index: '06', title: '建议 / 审批', tech: 'Advisory · SHA-256 原型审计链', desc: '当前不下发 SCADA；生产 WORM 库待建设' },
]

const STACK_LAYERS = [
  {
    id: 'data', label: '数据资产', status: '目标接入栈',
    title: '事件流 → 时空数据湖 → 训练轨迹',
    body: 'MQTT 接传感器与 SCADA；Kafka / Redpanda 承载事件流，Debezium 捕获变更，Flink 清洗并做事件时间对齐；TimescaleDB、PostGIS、MinIO、Redis 分别保存时序、空间、对象与最近状态。',
  },
  {
    id: 'state', label: '状态估计', status: '同化核心已具备 / 设备资源待接',
    title: '质量控制后的观测 → 不确定性信念状态',
    body: '当前由 spin-up 与局地 EnSRF 输出各区蓄水/水深集合及方差，并接收泵效与应急增排预算；完整设备遥测、资源位置和延迟观测治理属于目标接入范围。',
  },
  {
    id: 'world', label: '世界模型', status: '物理核心已运行',
    title: '物理守恒 + 可学习残差',
    body: 'NumPy 守恒图模型负责降雨产流、排水、区际汇流、外排、潮位顶托和水量账本；待真实事件数据成熟后，PyTorch / JAX 残差网络只修正可验证的系统偏差，Numba 与 Ray 用于批量推演加速。',
  },
  {
    id: 'decision', label: '决策优化', status: '稳健 CEM 已运行',
    title: '有限时域模型式搜索先行，强化学习影子评估',
    body: '当前后端以有限时域稳健 CEM 搜索十区排水控制并可随新快照滚动重算；Gymnasium、CasADi / CVXPY / OSQP 与严格分段 MPC 属于下一阶段。数据成熟后再评估 SAC / PPO / 残差 RL（SB3、RLlib、TorchRL）。',
  },
  {
    id: 'multi', label: '联合调度', status: '演进路线',
    title: '连续控制 + 离散资源 + 多区协同',
    body: '策略网络负责泵负荷、闸门开度和调蓄池目标水位，OR-Tools / MILP 负责泵车、封路和避险场所；多区耦合可用 GNN 编码汇流图，并以 CTDE 集中训练、分散执行。',
  },
  {
    id: 'ops', label: '安全与 MLOps', status: '安全边界已运行 / 平台栈待建',
    title: '安全盾、服务治理与逐动作审计',
    body: '当前动作先经过边界、变化率、总预算和成对集合无恶化投影，再进入人工审批；QP 投影属于设备约束齐备后的演进项。FastAPI + Pydantic 已承载接口，其余目标栈为 Kubernetes、gRPC、MLflow、BentoML / KServe、Prometheus / Grafana / OpenTelemetry 与 WORM 审计库。',
  },
]

const ROADMAP = [
  { label: 'Gymnasium 封装', status: 'planned' },
  { label: '奖励与硬约束', status: 'active' },
  { label: '稳健 CEM 基线', status: 'active' },
  { label: '离线 / 残差 RL', status: 'planned' },
  { label: '影子运行', status: 'planned' },
  { label: '建议模式', status: 'active' },
  { label: '有限闭环', status: 'guarded' },
]

const REWARD_LABELS = {
  flood: '积水损失', severe: '严重超阈', uncertainty: '不确定性', energy: '能源成本',
  mobilization: '调度成本', accessibility: '可达性', exposure: '暴露损失', total: '综合目标',
  flood_cost: '积水损失', severe_cost: '严重超阈', uncertainty_cost: '不确定性',
  energy_cost: '能源成本', mobilization_cost: '调度成本', objective: '综合目标',
}

const METRIC_DEFS = [
  { key: 'peak', label: '城市峰值 P50', paths: ['city_peak_depth_p50_m', 'peak_depth_m', 'city_peak_depth_m', 'metrics.peak_depth_m', 'max_depth_m'], unit: 'm', lower: true },
  { key: 'severe', label: '超 15cm 概率', paths: ['max_probability_gt_0_15m', 'severe_probability', 'prob_depth_ge_15cm', 'threshold_probability', 'metrics.prob_depth_ge_15cm'], unit: '%', probability: true, lower: true },
  { key: 'access', label: '关键设施可达', paths: ['accessibility', 'city_reachable_pop_share', 'metrics.accessibility'], unit: '%', probability: true, lower: false },
  { key: 'objective', label: '综合代价', paths: ['objective.total_cost', 'objective_cost', 'total_cost', 'metrics.objective'], unit: '', lower: true },
]

function finite(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function nested(object, path) {
  return path.split('.').reduce((value, key) => value?.[key], object)
}

function firstValue(object, paths) {
  for (const path of paths) {
    const value = finite(nested(object, path))
    if (value !== null) return value
  }
  return null
}

function fmt(value, definition) {
  const number = finite(value)
  if (number === null) return '—'
  if (definition.probability) return `${(number <= 1 ? number * 100 : number).toFixed(1)}%`
  if (definition.unit === 'm') return `${number.toFixed(3)} m`
  return `${number.toFixed(Math.abs(number) >= 100 ? 0 : 2)}${definition.unit ? ` ${definition.unit}` : ''}`
}

function fmtControl(value) {
  const number = finite(value)
  return number === null ? '—' : `×${number.toFixed(2)}`
}

function normalizeRewardRows(value) {
  if (!value) return []
  if (Array.isArray(value)) {
    return value.map((item, index) => ({
      key: item.key || item.id || `part-${index}`,
      label: item.label || REWARD_LABELS[item.key] || item.key || `分项 ${index + 1}`,
      baseline: finite(item.baseline), optimized: finite(item.optimized), delta: finite(item.delta ?? item.reward),
    }))
  }
  const source = value.components || value
  if (source.baseline && source.optimized) {
    const keys = [...new Set([...Object.keys(source.baseline), ...Object.keys(source.optimized)])]
    return keys.map((key) => {
      const baseline = finite(source.baseline[key])
      const optimized = finite(source.optimized[key])
      return { key, label: REWARD_LABELS[key] || key, baseline, optimized, delta: baseline !== null && optimized !== null ? baseline - optimized : null }
    })
  }
  return Object.entries(source)
    .filter(([, item]) => typeof item === 'number' || (item && typeof item === 'object'))
    .map(([key, item]) => {
      if (typeof item === 'number') return { key, label: REWARD_LABELS[key] || key, baseline: null, optimized: null, delta: item }
      const baseline = finite(item.baseline ?? item.before)
      const optimized = finite(item.optimized ?? item.after)
      return {
        key, label: item.label || REWARD_LABELS[key] || key, baseline, optimized,
        delta: finite(item.delta ?? item.reward) ?? (baseline !== null && optimized !== null ? baseline - optimized : null),
      }
    })
}

function constraintEntries(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.map((item, index) => [item.name || item.id || `约束 ${index + 1}`, item.value ?? item.status ?? item])
  return Object.entries(value).filter(([, item]) => typeof item !== 'object' || item === null)
}

function humanize(key) {
  const labels = {
    min_control: '最小排水控制', max_control: '最大排水控制', max_first_step_change: '首步动作变化上限',
    emergency_budget_mm_h: '应急增排预算', hard_violations: '硬约束违例', feasible: '投影后可行',
    forecast_run_id: '预报快照', optimization_run_id: '优化运行', world_model_version: '世界模型',
    decision_run_id: '决策运行', digest_sha256: '审计摘要', storage: '审计存储',
    decision_fingerprint: '决策指纹',
    policy_type: '策略类型', planner: '优化器', seed: '随机种子', generated_at: '生成时间',
  }
  return labels[key] || key.replaceAll('_', ' ')
}

function displayValue(key, value) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value === null || value === undefined) return '—'
  if (key.includes('control') && Number.isFinite(Number(value))) return fmtControl(value)
  if (key.includes('budget') && Number.isFinite(Number(value))) return `${Number(value).toFixed(0)} mm/h`
  return String(value)
}

function displayAuditValue(value) {
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function MetricCard({ definition, baseline, optimized }) {
  const before = firstValue(baseline, definition.paths)
  const after = firstValue(optimized, definition.paths)
  if (before === null && after === null) return null
  const rawDelta = before !== null && after !== null ? after - before : null
  const positive = rawDelta !== null && (definition.lower ? rawDelta < 0 : rawDelta > 0)
  const deltaDefinition = { ...definition, probability: false }
  let deltaLabel = '等待对比'
  if (rawDelta !== null) {
    if (definition.probability) {
      const pctPoints = (before <= 1 && after <= 1 ? rawDelta * 100 : rawDelta)
      deltaLabel = `${pctPoints > 0 ? '+' : ''}${pctPoints.toFixed(1)} pp`
    } else {
      deltaLabel = `${rawDelta > 0 ? '+' : ''}${fmt(rawDelta, deltaDefinition)}`
    }
  }
  return (
    <div className="wamx-metric">
      <div className="wamx-metric-label">{definition.label}</div>
      <div className="wamx-metric-values"><span>{fmt(before, definition)}</span><i>→</i><b>{fmt(after, definition)}</b></div>
      <div className={`wamx-delta ${rawDelta === null ? '' : positive ? 'good' : rawDelta === 0 ? 'flat' : 'bad'}`}>{deltaLabel}</div>
    </div>
  )
}

export default function WamOptimizationPanel({ predictData }) {
  const [horizon, setHorizon] = useState(24)
  const [profile, setProfile] = useState('balanced')
  const [budget, setBudget] = useState('standard')
  const [result, setResult] = useState(null)
  const [appliedConfig, setAppliedConfig] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const requestRef = useRef(0)
  const forecastDays = Math.min(7, Math.max(1, Number(predictData?.forecast_days) || 3))
  const forecastRunId = predictData?.forecast_run_id || null

  async function optimize() {
    const requestId = ++requestRef.current
    const expectedRunId = forecastRunId
    const search = SEARCH_BUDGETS[budget]
    setLoading(true)
    setError(null)
    setResult(null)
    setAppliedConfig(null)
    try {
      const requestPayload = {
        ...(expectedRunId ? { forecast_run_id: expectedRunId } : {}),
        forecast_days: forecastDays,
        horizon_hours: Number(horizon),
        planner: {
          method: 'robust_cem_constant_hold', population: search.population, iterations: search.iterations,
          elite_fraction: 0.2, seed: 20260824,
        },
        objective_weights: RISK_PROFILES[profile].weights,
        constraints: {
          min_control: 0.75, max_control: 1.25, max_first_step_change: 0.25, emergency_budget_mm_h: 45,
        },
        pump_efficiency: 1,
      }
      const response = await postWamOptimize(requestPayload)
      const responseRunId = response?.forecast_run_id || response?.audit?.forecast_run_id
      if (expectedRunId && responseRunId !== expectedRunId) {
        throw new Error(responseRunId
          ? `优化结果快照不一致（请求 ${expectedRunId.slice(0, 12)}，响应 ${String(responseRunId).slice(0, 12)}），已拒绝展示。`
          : '优化响应缺少 forecast_run_id，无法确认其与当前预报快照一致，已拒绝展示。')
      }
      if (requestId === requestRef.current) {
        setResult(response)
        setAppliedConfig({
          horizon: finite(response?.horizon_hours) ?? requestPayload.horizon_hours,
          requestedHorizon: finite(response?.requested_horizon_hours) ?? requestPayload.horizon_hours,
          truncated: response?.horizon_truncated_to_snapshot === true,
          profile: RISK_PROFILES[profile].label,
          budget: SEARCH_BUDGETS[budget].label,
          population: requestPayload.planner.population,
          iterations: requestPayload.planner.iterations,
        })
      }
    } catch (cause) {
      if (requestId === requestRef.current) setError(cause?.message || '动作优化失败')
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    if (!forecastRunId) {
      requestRef.current += 1
      setResult(null)
      setAppliedConfig(null)
      setError(null)
      setLoading(false)
      return
    }
    setResult(null)
    setAppliedConfig(null)
    setError(null)
    optimize()
    // A new signed forecast snapshot should receive its own optimization run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forecastRunId])

  const baseline = result?.baseline || result?.comparison?.baseline || {}
  const optimized = result?.optimized || result?.comparison?.optimized || {}
  const actions = result?.action_plan || result?.actions || result?.safe_actions || []
  const rewardRows = useMemo(() => normalizeRewardRows(result?.reward_breakdown || result?.objective_breakdown || result?.reward), [result])
  const rewardMax = Math.max(1e-9, ...rewardRows.map((row) => Math.abs(row.delta || 0)))
  const adjustedActions = actions.filter((action) => {
    const requested = finite(action.requested_control ?? action.requested ?? action.raw_action)
    const projected = finite(action.projected_control ?? action.projected ?? action.safe_action)
    return requested !== null && projected !== null && Math.abs(requested - projected) > 1e-6
  })
  const safety = result?.safety_projection || result?.safety || {}
  const constraints = result?.constraints || {}
  const audit = result?.audit || {}
  const auditEntries = Object.entries({
    forecast_run_id: audit.forecast_run_id || result?.forecast_run_id,
    optimization_run_id: audit.optimization_run_id || result?.optimization_run_id || result?.run_id,
    decision_run_id: audit.decision_run_id,
    decision_fingerprint: audit.decision_fingerprint || result?.decision_fingerprint,
    world_model_version: audit.world_model_version || result?.world_model_version,
    planner: audit.planner || result?.optimizer,
    seed: audit.seed,
    digest_sha256: audit.digest_sha256,
    storage: audit.storage,
    generated_at: audit.generated_at || result?.generated_at,
  }).filter(([, value]) => value !== null && value !== undefined && value !== '')
  const policyType = result?.policy_type || audit.policy_type || 'model_based_robust_cem_constant_hold_baseline'
  const policyLabel = policyType === 'model_based_robust_cem_constant_hold_baseline'
    ? '可解释稳健 CEM 常值保持基线'
    : policyType
  const rlStatus = result?.rl_status || audit.rl_status || 'not_trained_not_deployed'
  const executionMode = result?.execution_mode || 'advisory_only'
  const safetyFeasible = safety.feasible ?? safety.constraints_satisfied ?? safety.projected_feasible ?? result?.feasible
  const hardViolations = finite(safety.hard_violations ?? safety.constraint_violations ?? result?.hard_violations)

  return (
    <section id="wam-optimize" className="card wamx" aria-labelledby="wamx-title">
      <header className="wamx-head">
        <div>
          <div className="wamx-kicker">AUTONOMOUS ACTION OPTIMIZATION · SAFE WAM</div>
          <div className="wamx-title-row">
            <h2 id="wamx-title">自主优化 WAM · 安全决策闭环</h2>
            <span className="wamx-mode-badge">建议模式 · 不自动下发</span>
          </div>
          <p>世界模型负责可信推演，当前由有限时域稳健 CEM 搜索动作并经安全盾验证；强化学习仅在有足够真实轨迹后进入影子评估。</p>
        </div>
        <div className="wamx-run-meta">
          <span>FORECAST SNAPSHOT</span>
          <b title={forecastRunId || '尚无快照'}>{forecastRunId ? forecastRunId.slice(0, 18) : '—'}</b>
        </div>
      </header>

      <div className="wamx-loop" aria-label="自主优化决策流程">
        {LOOP_STAGES.map((stage, index) => (
          <div className="wamx-stage-wrap" key={stage.id}>
            <div className={`wamx-stage ${stage.id}`}>
              <span className="wamx-stage-index">{stage.index}</span>
              <div><b>{stage.title}</b><em>{stage.tech}</em><small>{stage.desc}</small></div>
            </div>
            {index < LOOP_STAGES.length - 1 && <span className="wamx-arrow" aria-hidden="true">›</span>}
          </div>
        ))}
      </div>

      <div className="wamx-contract" aria-label="WAM 决策契约">
        <div><span>W · WORLD</span><b>十区守恒图状态转移</b><small>降雨、潮位、汇流、排水、外排</small></div>
        <div><span>S · STATE</span><b>当前集合信念状态</b><small>初始水深 / 降雨 / 潮位 / 泵效 / 方差</small></div>
        <div><span>A · ACTION</span><b>当前十区排水控制倍率</b><small>闸门、泵车与封路属于后续离散调度</small></div>
        <div><span>R · REWARD</span><b>当前风险—成本目标</b><small>积水、严重超阈、不确定性、能耗、调度变化</small></div>
      </div>

      <div className="wamx-controlbar">
        <label>
          <span>滚动时域</span>
          <select disabled={loading} value={horizon} onChange={(event) => { setHorizon(Number(event.target.value)); setResult(null); setAppliedConfig(null); setError(null) }}>
            <option value={12}>未来 12 小时</option><option value={24}>未来 24 小时</option><option value={48}>未来 48 小时</option><option value={72}>未来 72 小时</option>
          </select>
        </label>
        <label>
          <span>目标偏好</span>
          <select disabled={loading} value={profile} onChange={(event) => { setProfile(event.target.value); setResult(null); setAppliedConfig(null); setError(null) }}>
            {Object.entries(RISK_PROFILES).map(([key, item]) => <option value={key} key={key}>{item.label}</option>)}
          </select>
        </label>
        <label>
          <span>搜索预算</span>
          <select disabled={loading} value={budget} onChange={(event) => { setBudget(event.target.value); setResult(null); setAppliedConfig(null); setError(null) }}>
            {Object.entries(SEARCH_BUDGETS).map(([key, item]) => <option value={key} key={key}>{item.label}</option>)}
          </select>
        </label>
        <button className="wamx-optimize" onClick={optimize} disabled={loading || !forecastRunId}>
          {loading ? <><i className="wamx-spinner" /> 正在滚动搜索…</> : '运行安全动作优化'}
        </button>
      </div>

      {error && (
        <div className="wamx-error" role="alert"><b>优化器暂不可用</b><span>{error}</span><button onClick={optimize}>重试</button></div>
      )}

      {!result && !error && (
        <div className="wamx-pending"><i className="wamx-spinner" /><span>{loading ? '正在以同一预报快照并行推演候选动作…' : '等待有效预报快照后启动动作优化。'}</span></div>
      )}

      {result && (
        <>
          <SubmitDecisionButton result={result} />
          <div className="wamx-trustline">
            <span className="ok-dot" />
            <b>{policyLabel}</b>
            <span>执行：{executionMode === 'advisory_only' ? '仅建议' : executionMode}</span>
            <span>RL：{rlStatus === 'not_trained_not_deployed' ? '未训练、未部署' : rlStatus}</span>
            <span>动作：时域内常值保持 · 非序列 MPC</span>
            <span>候选：{result?.audit?.candidate_count ?? result?.candidate_count ?? '—'}</span>
            {appliedConfig && <span>已应用：{appliedConfig.horizon}h{appliedConfig.truncated ? `（请求 ${appliedConfig.requestedHorizon}h，按快照截断）` : ''} · {appliedConfig.profile} · {appliedConfig.population}×{appliedConfig.iterations}</span>}
          </div>

          <div className="wamx-result-grid">
            <div className="wamx-result-card comparison">
              <div className="wamx-section-h"><span>01</span><div><b>基线 vs 优化后</b><small>同预报、同状态、同参数集合的公平反事实</small></div></div>
              <div className="wamx-metrics">
                {METRIC_DEFS.map((definition) => <MetricCard key={definition.key} definition={definition} baseline={baseline} optimized={optimized} />)}
              </div>
              {!METRIC_DEFS.some((definition) => firstValue(baseline, definition.paths) !== null || firstValue(optimized, definition.paths) !== null) && (
                <div className="wamx-empty">后端已完成优化，但本次响应没有可展示的城市对比指标。</div>
              )}
            </div>

            <div className="wamx-result-card reward">
              <div className="wamx-section-h"><span>02</span><div><b>目标 / 奖励分解</b><small>正值表示相对基线减少的代价</small></div></div>
              <div className="wamx-reward-list">
                {rewardRows.map((row) => (
                  <div className="wamx-reward-row" key={row.key}>
                    <span>{row.label}</span>
                    <i><u style={{ width: `${Math.max(3, Math.abs(row.delta || 0) / rewardMax * 100)}%` }} /></i>
                    <b className={(row.delta || 0) >= 0 ? 'good' : 'bad'}>{row.delta === null ? '—' : `${row.delta > 0 ? '+' : ''}${row.delta.toFixed(2)}`}</b>
                  </div>
                ))}
                {!rewardRows.length && <div className="wamx-empty">本次响应未返回奖励分解。</div>}
              </div>
            </div>

            <div className="wamx-result-card safety">
              <div className="wamx-section-h"><span>03</span><div><b>安全投影与硬约束</b><small>RL / 优化器意图不能绕过安全盾</small></div></div>
              <div className="wamx-safety-kpis">
                <div><span>建议动作</span><b>{actions.length}</b></div>
                <div><span>被安全层修正</span><b>{adjustedActions.length}</b></div>
                <div><span>投影后可行</span><b className={safetyFeasible === true ? 'good' : safetyFeasible === false ? 'bad' : ''}>{safetyFeasible === null || safetyFeasible === undefined ? '未证实' : safetyFeasible ? '是' : '否'}</b></div>
                <div><span>硬约束违例</span><b className={hardViolations === null ? '' : hardViolations > 0 ? 'bad' : 'good'}>{hardViolations ?? '未返回'}</b></div>
              </div>
              <div className="wamx-constraint-list">
                {constraintEntries(constraints).map(([key, value]) => <div key={key}><span>{humanize(key)}</span><b>{displayValue(key, value)}</b></div>)}
              </div>
            </div>
          </div>

          <div className="wamx-actions">
            <div className="wamx-section-h"><span>04</span><div><b>安全动作建议</b><small>请求动作 → 安全投影动作；所有结果均需审批后由既有业务系统执行</small></div></div>
            <div className="wamx-action-head"><span>区域 / 动作</span><span>优化器请求</span><span>安全投影</span><span>有效能力</span><span>原因与审批</span></div>
            {actions.map((action, index) => {
              const requested = action.requested_control ?? action.requested ?? action.raw_action
              const projected = action.projected_control ?? action.projected ?? action.safe_action
              const changed = finite(requested) !== null && finite(projected) !== null && Math.abs(Number(requested) - Number(projected)) > 1e-6
              return (
                <div className="wamx-action-row" key={`${action.district_id || action.id || index}-${index}`}>
                  <div><b>{action.district_name || action.name || action.district_id || `动作 ${index + 1}`}</b><small>{action.action_type || '排水控制倍率'}</small></div>
                  <span>{fmtControl(requested)}</span>
                  <span className={changed ? 'projected' : 'accepted'}>{fmtControl(projected)}{changed && <small>安全层修正</small>}</span>
                  <span>{finite(action.effective_capacity_mm_h) === null ? '—' : `${Number(action.effective_capacity_mm_h).toFixed(1)} mm/h`}</span>
                  <div className="wamx-action-reason"><span>{action.reason || '滚动时域综合代价较低'}</span><b>{action.approval_required === false ? '低风险候选' : '需人工审批'}</b></div>
                </div>
              )
            })}
            {!actions.length && <div className="wamx-empty">优化器未建议改变当前控制状态。</div>}
          </div>

          <div className="wamx-audit">
            <div><span className="wamx-audit-mark">AUDIT</span><b>决策证据链</b><small>观测、状态、天气版本、推演、动作、安全修正与审批状态可回放</small></div>
            <dl>{auditEntries.map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd title={displayAuditValue(value)}>{displayAuditValue(value)}</dd></div>)}</dl>
          </div>
        </>
      )}

      <details className="wamx-stack" open>
        <summary><span>完整技术栈与七步上线纪律</span><small>展开 / 收起架构实现边界</small></summary>
        <div className="wamx-stack-grid">
          {STACK_LAYERS.map((layer) => (
            <article key={layer.id} className={layer.id}>
              <div><span>{layer.label}</span><i>{layer.status}</i></div><b>{layer.title}</b><p>{layer.body}</p>
            </article>
          ))}
        </div>
        <div className="wamx-roadmap">
          {ROADMAP.map((item, index) => <div key={item.label} className={item.status}><span>{index + 1}</span><b>{item.label}</b></div>)}
        </div>
        <div className="wamx-principle">
          <b>未来训练数据要求：</b>独立历史暴雨事件 + 人工调度记录 + 优化器专家轨迹 + domain-randomized 模拟；当前数据尚不满足 RL 训练声明。
          <b>上线原则：</b>先证明稳健 CEM / MPC 优于规则，再让离线 / 残差 RL 在影子模式小幅超越；只有低风险动作可进入有限闭环，高风险动作长期保留人工审批。
        </div>
      </details>
    </section>
  )
}


/* ============ 提交为决策建议（人工审批闭环） ============ */

function SubmitDecisionButton({ result }) {
  const [state, setState] = useState('idle') // idle | busy | done | err
  const [msg, setMsg] = useState('')

  async function submit() {
    setState('busy')
    setMsg('')
    try {
      // 从优化结果提取方案摘要与控制动作
      const actions = (result?.recommended_actions || result?.actions || []).slice(0, 10).map((a) => ({
        district: a.district || a.district_id || '全市',
        action: a.action || 'control',
        value: a.control ?? a.value ?? a.first_step ?? null,
        expected_effect: a.expected_effect || null,
      }))
      const peak = result?.metrics?.flood?.peak_mm
        ?? result?.objective?.components?.flood
        ?? result?.expected_flood_peak_mm
      const summaryParts = [
        `WAM ${result?.method || 'CEM'} 优化建议`,
        actions.length ? `含 ${actions.length} 项分区控制动作` : '无控制动作',
        peak != null ? `预期内涝峰值 ${typeof peak === 'number' ? peak.toFixed(1) : peak}mm` : '',
      ].filter(Boolean)
      const r = await fetch('/api/decisions/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_summary: summaryParts.join(' · '),
          control_actions: actions,
          expected_flood_peak_mm: typeof peak === 'number' ? peak : null,
          method: result?.method || 'robust_cem_constant_hold',
        }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '提交失败')
      setState('done')
      setMsg(`已提交 ${d.id} → 待人工决策`)
    } catch (e) {
      setState('err')
      setMsg(e.message)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
      <button
        className="btn sm primary"
        onClick={submit}
        disabled={state === 'busy' || state === 'done'}
      >
        {state === 'busy' ? '提交中…' : state === 'done' ? '✓ 已提交决策队列' : '📋 提交为决策建议（人工审批）'}
      </button>
      {msg && (
        <span style={{ fontSize: 11, color: state === 'err' ? 'var(--danger)' : 'var(--ok)' }}>{msg}</span>
      )}
    </div>
  )
}
