import { useEffect, useState } from 'react'
import { getHazardsSummary } from '../api'
import SurgePanel from './SurgePanel.jsx'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

/**
 * SurgePage — 风暴潮灾害页
 * 潮位站统计 + 四大事件波浪峰值 + 3D 海洋点位
 */
export default function SurgePage() {
  // 实时面板（谐波推算 + 增水）+ 历史统计
  const [realtime] = useState(true)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    getHazardsSummary().then(setData).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div className="card"><div className="err-box">⚠ {err}</div></div>
  if (!data) return <div className="card"><div className="loading">加载风暴潮数据…</div></div>

  const su = data.surge || {}
  const stations = su.stations || []
  const waves = (su.wave_events || []).slice()

  const waveChart = waves.map((w) => ({
    name: w.event_name,
    max: w.max_swh_m,
    大鹏湾口: w.by_point?.['大鹏湾口外海'] ?? null,
    珠江口: w.by_point?.['珠江口'] ?? null,
    深圳湾: w.by_point?.['深圳湾'] ?? null,
  }))

  return (
    <>
      <SurgePanel />
      <div className="surge-page">
      <div className="page-head">
        <h2>🌊 风暴潮灾害</h2>
        <p className="page-desc">
          香港天文台验潮站天文潮（基准面 CD）+ CMEMS WAVERYS 波浪再分析。
          潮位与深圳 1985 国家高程基准未经换算不可直接合并（诚实标注）。
        </p>
      </div>

      {/* 潮位站卡片 */}
      <div className="hazard-cards">
        {stations.map((s) => (
          <div key={s.station_id} className="hazard-card surge">
            <div className="hc-head">{s.name}</div>
            <div className="hc-big">{s.max_tide_m}m</div>
            <div className="hc-sub">最大天文潮（{s.years?.join('/')}）</div>
            <div className="hc-meta">
              <span className="hc-chip">平均 {s.mean_tide_m}m</span>
              <span className="hc-chip">潮差 {s.tidal_range_m}m</span>
              <span className="hc-chip">基准 {s.datum}</span>
            </div>
            <div className="hc-src">({s.lat}, {s.lon})</div>
          </div>
        ))}
      </div>

      {/* 波浪事件图表 */}
      <div className="card">
        <div className="panel-title">四大事件最大波高对比（米）</div>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={waveChart}>
            <XAxis dataKey="name" stroke="#9ab" />
            <YAxis stroke="#9ab" unit="m" />
            <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
            <Bar dataKey="max" radius={[6, 6, 0, 0]}>
              {waveChart.map((entry, i) => (
                <Cell key={i} fill={entry.max >= 8 ? '#b3122b' : entry.max >= 4 ? '#d6452a' : entry.max >= 2 ? '#e08a1e' : '#37c8c3'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* 各点位波浪详情 */}
      <div className="card">
        <div className="panel-title">各近岸点波高详情</div>
        <table className="mini-table">
          <thead><tr><th>事件</th><th>大鹏湾口外海</th><th>珠江口</th><th>深圳湾</th></tr></thead>
          <tbody>
            {waveChart.map((w) => (
              <tr key={w.name}>
                <td>{w.name}</td>
                <td>{w['大鹏湾口'] ?? '—'} m</td>
                <td>{w['珠江口'] ?? '—'} m</td>
                <td>{w['深圳湾'] ?? '—'} m</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="footnote">
          波高数据来自 CMEMS WAVERYS 再分析（卫星高度计同化）；山竹 2018 期间大鹏湾口外海达 9.51m。
        </div>
      </div>
    </div>
  </>
  )
}