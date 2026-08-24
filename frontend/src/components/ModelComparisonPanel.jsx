import { useEffect, useState } from 'react'
import { getBenchmark } from '../api'

export default function ModelComparisonPanel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const d = await getBenchmark()
      setData(d)
    } catch (e) { setErr(e.message || '加载失败') } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const cols = [
    ['auc', 'AUC'], ['brier', 'Brier'], ['hit_rate', '命中率'],
    ['miss_rate', '漏报率'], ['false_alarm_rate', '误报率'], ['mean_lead_time_h', '提前量'],
  ]
  const benchmark = data?.benchmark
  const independentlyValidated = data?.status === 'ok' && (
    data.independently_validated === true
    || data.validation_basis === 'independent_observed_events'
    || benchmark?.independently_validated === true
  )
  const readiness = data?.data_readiness || data?.readiness || {}
  const candidates = data?.candidates || [
    { id: 'ensemble_enkf', role: '当前候选主模型', description: '可审计质量守恒、潮位/抽排干预和集合不确定性', requires_training: false },
    { id: 'persistence', role: '待事件数据齐备', description: '所有学习模型必须超过的简单参照', requires_training: false },
    { id: 'spatiotemporal', role: '研究候选', description: '等待足量事件级真值后再做时间外比较', requires_training: true },
  ]
  const candidateNames = {
    zero_or_climatology: '零积水 / 气候态基线',
    rain_threshold: '降雨阈值基线',
    persistence: '持续性基线',
    conservative_state_space: '守恒状态空间（无同化）',
    state_space_no_assimilation: '守恒状态空间（无同化）',
    ensemble_enkf: '守恒集合 + 局地 EnSRF',
    gradient_boosted_residual: '梯度提升物理残差',
    spatiotemporal_neural_operator: '图时空/神经状态空间',
  }

  return (
    <section className="card stage">
      <div className="card-h">
        模型评估矩阵
        <span className="hint">守恒状态空间模型 · 持续性/统计基线 · 数据驱动候选</span>
        <button className="mini" onClick={load} disabled={loading}>{loading ? '刷新中…' : '↻ 刷新就绪度'}</button>
      </div>
      {err && <div className="empty">{err}</div>}
      {data && !independentlyValidated && (
        <>
          <div className="status-banner limited">
            <b>暂不发布 LSTM / Transformer 准确率排名</b>
            <span>{data.hint || readiness.reason || '缺少独立洪涝事件标签，现有分数不能用于模型选型。'}</span>
          </div>
          <div className="candidate-grid">
            {candidates.map((candidate, index) => (
              <div className={`candidate ${candidate.id === 'ensemble_enkf' ? 'active' : (candidate.requires_training ? 'blocked' : 'pending')}`} key={candidate.id || index}>
                <b>{candidate.name || candidateNames[candidate.id] || candidate.id}</b>
                <span>{candidate.role || (candidate.requires_training ? '需要独立训练数据' : '无需训练')}</span>
                <small>{candidate.description}</small>
              </div>
            ))}
          </div>
          <div className="mc-note">现阶段的“更高级”来自状态、边界、守恒和不确定性的正确表达，不是在伪标签上堆叠更复杂的网络。</div>
        </>
      )}
      {benchmark && independentlyValidated && (
        <>
          <div className="cmp-table">
            <div className="cmp-row cmp-head">
              <span>模型</span>
              {cols.map(([k, l]) => <span key={k}>{l}</span>)}
              <span>最优</span>
            </div>
            {benchmark.models.map((m) => (
              <div className="cmp-row" key={m.type}>
                <span className="cmp-type">{m.type === 'lstm' ? 'LSTM' : 'Transformer'}</span>
                {cols.map(([k, l]) => (
                  <span key={k} className={k === 'auc' && m.type === benchmark.best.type ? 'best' : ''}>
                    {k === 'mean_lead_time_h' ? (m[k] != null ? `${m[k]}h` : '—') : m[k]}
                  </span>
                ))}
                <span>{m.type === benchmark.best.type ? '★' : ''}</span>
              </div>
            ))}
          </div>
          <div className="mc-note">{benchmark.note}（{benchmark.n_test} 测试样本）</div>
        </>
      )}
    </section>
  )
}
