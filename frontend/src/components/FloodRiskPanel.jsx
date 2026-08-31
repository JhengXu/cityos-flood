import { useEffect, useState } from 'react'
import { fetchJSON } from '../api'

/**
 * FloodRiskPanel — 内涝概率桶可视化（P10/P50/P90 + 超阈概率）
 * 集合模拟（50 成员参数不确定）→ 各分区风险条 + 概率分级
 */
const LEVEL_COLORS = {
  high: 'var(--danger)',
  mid: 'var(--warn)',
  low: 'var(--ok)',
}

function riskLevel(mm) {
  if (mm >= 50) return { label: '高风险', color: LEVEL_COLORS.high }
  if (mm >= 15) return { label: '中风险', color: LEVEL_COLORS.mid }
  return { label: '低风险', color: LEVEL_COLORS.low }
}

export default function FloodRiskPanel() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    fetchJSON('/api/live').then(setData).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div className="err-box">⚠ {err}</div>
  if (!data) return null

  const fq = data.flood_quantiles || {}
  const districts = Object.entries(fq)
  // 按 P50 峰值排序
  districts.sort((a, b) => b[1].p50_peak_mm - a[1].p50_peak_mm)
  const maxP50 = Math.max(...districts.map(([, q]) => q.p50_peak_mm), 1)

  if (!districts.length) {
    return (
      <div className="card" style={{ padding: '12px 16px' }}>
        <span className="footnote">内涝概率桶数据不可用</span>
      </div>
    )
  }

  // 全城最高风险
  const worst = districts[0][1]
  const worstLvl = riskLevel(worst.p50_peak_mm)

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="card-h">
        🌧️ 内涝概率桶（集合模拟 P10/P50/P90）
        <span className="hint">50 成员参数不确定 · 守恒模型</span>
      </div>

      <div style={{ padding: '10px 14px', display: 'flex', gap: 8, flexWrap: 'wrap', borderBottom: '1px solid var(--line-soft)' }}>
        <span className="chip" style={{ color: worstLvl.color, borderColor: `color-mix(in srgb, ${worstLvl.color} 40%, transparent)` }}>
          全城最高 {worstLvl.label}（{worst.district_name} P50 {worst.p50_peak_mm}mm）
        </span>
        <span className="chip">P90 置信上限</span>
        <span className="chip">超阈概率标注</span>
      </div>

      {/* 分区条 */}
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {districts.map(([did, q]) => {
          const lvl = riskLevel(q.p50_peak_mm)
          const excPct = q.exc_15mm > 0 ? (q.exc_15mm * 100).toFixed(0) : null
          return (
            <div key={did} style={{ display: 'grid', gridTemplateColumns: '64px minmax(0,1fr) 150px 44px', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{q.district_name}</span>
              {/* P10-P90 区间条 */}
              <div style={{ position: 'relative', height: 14, background: 'var(--panel-3)', borderRadius: 4, overflow: 'hidden' }}>
                {/* P10-P90 区间 */}
                <div style={{
                  position: 'absolute', top: 1, bottom: 1,
                  left: `${(q.p10_peak_mm / maxP50) * 100}%`,
                  width: `${Math.max((q.p90_peak_mm - q.p10_peak_mm) / maxP50, 0.01) * 100}%`,
                  background: `color-mix(in srgb, ${lvl.color} 25%, transparent)`,
                  borderRadius: 3,
                }} />
                {/* P50 中位线 */}
                <div style={{
                  position: 'absolute', top: 0, bottom: 0, width: 2,
                  left: `${(q.p50_peak_mm / maxP50) * 100}%`,
                  background: lvl.color, borderRadius: 2,
                }} />
              </div>
              {/* P50 数值 */}
              <div style={{ display: 'flex', gap: 8, fontSize: 11, alignItems: 'baseline' }}>
                <span className="mono" style={{ fontWeight: 700, color: lvl.color }}>{q.p50_peak_mm}mm</span>
                <span className="mono" style={{ color: 'var(--ink-4)', fontSize: 10 }}>P90 {q.p90_peak_mm}</span>
              </div>
              {/* 风险徽章 */}
              <span className="chip" style={{ color: lvl.color, fontSize: 10, padding: '1px 8px' }}>
                {excPct ? `>15mm ${excPct}%` : lvl.label}
              </span>
            </div>
          )
        })}
      </div>

      <div style={{ padding: '0 14px 12px' }}>
        <p className="footnote">集合模拟反映参数不确定性（产流/排水/蓄滞/外排）；P10-P90 区间越宽代表该分区预测越不确定。超阈概率为 P(积水&gt;15mm)。</p>
      </div>
    </div>
  )
}
