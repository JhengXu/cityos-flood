import { useEffect, useState } from 'react'
import { fetchJSON } from '../api'

/**
 * FloodProfilePanel — 城市分区内涝风险画像
 * 历史易涝密度(2019官方) × 实时P50预测 → 综合风险分级
 */
const LEVEL_COLOR = {
  '高风险': 'var(--danger)',
  '中风险': 'var(--warn)',
  '低风险': 'var(--ok)',
}

export default function FloodProfilePanel() {
  const [data, setData] = useState(null)

  useEffect(() => {
    fetchJSON('/api/knowledge/flood-profile').then(setData).catch(() => setData(null))
  }, [])

  if (!data) return null
  const districts = data.districts || []
  const maxPts = Math.max(...districts.map((d) => d.flood_points_2019), 1)

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="card-h">
        🗺️ 分区内涝风险画像
        <span className="hint">{data.note}</span>
      </div>
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {districts.map((d) => (
          <div key={d.district_id} style={{ display: 'grid', gridTemplateColumns: '64px minmax(0,1fr) 76px 60px', gap: 10, alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{d.name}</span>
            <div style={{ position: 'relative', height: 10, background: 'var(--panel-3)', borderRadius: 5, overflow: 'hidden' }}>
              <div style={{
                position: 'absolute', inset: '0 auto 0 0', width: `${(d.risk_score * 100).toFixed(0)}%`,
                background: `color-mix(in srgb, ${LEVEL_COLOR[d.risk_level_label]} 45%, transparent)`,
                borderRadius: 5,
              }} />
              <div style={{ position: 'absolute', top: 0, bottom: 0, width: 1, background: LEVEL_COLOR[d.risk_level_label] }} />
            </div>
            <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', textAlign: 'right' }}>
              易涝点 {d.flood_points_2019}
            </span>
            <span className="chip" style={{ color: LEVEL_COLOR[d.risk_level_label], fontSize: 10, justifyContent: 'center' }}>
              {d.risk_level_label}
            </span>
          </div>
        ))}
      </div>
      <div style={{ padding: '0 14px 12px' }}>
        <p className="footnote">{data.source}</p>
      </div>
    </div>
  )
}
