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
      if (d.status === 'ok') setData(d.benchmark)
      else setErr(d.hint || '加载失败')
    } catch (e) { setErr(e.message || '加载失败') } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const cols = [
    ['anc', 'AUC'], ['brier', 'Brier'], ['hit_rate', '命中率'],
    ['miss_rate', '漏报率'], ['false_alarm_rate', '误报率'], ['mean_lead_time_h', '提前量'],
  ]

  return (
    <section className="card stage">
      <div className="card-h">
        模型对比 · LSTM vs Transformer
        <span className="hint">同一数据/固定切分/种子下的端到端监督训练</span>
        <button className="mini" onClick={load} disabled={loading}>{loading ? '训练中…' : '↻ 重新对比'}</button>
      </div>
      {err && <div className="empty">{err}</div>}
      {data && (
        <>
          <div className="cmp-table">
            <div className="cmp-row cmp-head">
              <span>模型</span>
              {cols.map(([k, l]) => <span key={k}>{l}</span>)}
              <span>最优</span>
            </div>
            {data.models.map((m) => (
              <div className="cmp-row" key={m.type}>
                <span className="cmp-type">{m.type === 'lstm' ? 'LSTM' : 'Transformer'}</span>
                {cols.map(([k, l]) => (
                  <span key={k} className={k === 'anc' && m.type === data.best.type ? 'best' : ''}>
                    {k === 'mean_lead_time_h' ? (m[k] != null ? `${m[k]}h` : '—') : m[k]}
                  </span>
                ))}
                <span>{m.type === data.best.type ? '★' : ''}</span>
              </div>
            ))}
          </div>
          <div className="mc-note">{data.note}（{data.n_test} 测试样本）</div>
        </>
      )}
    </section>
  )
}
