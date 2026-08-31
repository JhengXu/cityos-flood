import { useEffect, useState } from 'react'
import { getCascadeTyphoon } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LineChart, Line, Legend } from 'recharts'

/**
 * CascadePanel — 多灾种链式预测面板（台风 → 降雨 → 滑坡）
 * 嵌入台风页：选中台风后自动跑链式预测
 */
export default function CascadePanel({ selected }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (!selected?.name) return
    setLoading(true)
    setErr(null)
    getCascadeTyphoon(selected.name, selected.sid)
      .then(setData)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [selected?.name, selected?.sid])

  if (!selected) return null
  if (loading) return <div className="card"><div className="loading">链式预测计算中：台风 → 降雨场 → 滑坡概率…</div></div>
  if (err) return <div className="card"><div className="err-box">⚠ {err}</div></div>
  if (!data) return null

  const peaks = data.district_peak || []
  const ty = data.typhoon || {}

  // 山区区（滑坡高风险）+ 沿海区（内涝高风险）日序列
  const focusDistricts = ['盐田区', '大鹏新区', '龙岗区']
  const floodDistricts = ['宝安区', '南山区', '福田区']
  const districtNames = new Set((data.daily || []).map((r) => r.district_name))
  const focus = focusDistricts.filter((d) => districtNames.has(d))
  const floodFocus = floodDistricts.filter((d) => districtNames.has(d))
  const dailyByDistrict = {}
  for (const r of data.daily || []) {
    if (focus.includes(r.district_name) || floodFocus.includes(r.district_name)) {
      dailyByDistrict[r.district_name] = dailyByDistrict[r.district_name] || []
      dailyByDistrict[r.district_name].push({
        date: r.date.slice(5),
        rain: r.rain_24h,
        prob: +(r.landslide_warning_prob * 100).toFixed(1),
        flood: r.flood_depth_mm ?? 0,
      })
    }
  }
  // 滑坡线图数据（山区）
  const slideDates = [...new Set(
    focus.map((d) => dailyByDistrict[d] || []).flat().map((x) => x.date)
  )].sort()
  const slideData = slideDates.map((date) => {
    const row = { date }
    for (const name of focus) {
      const hit = (dailyByDistrict[name] || []).find((x) => x.date === date)
      row[name] = hit ? hit.prob : null
    }
    return row
  })
  // 内涝柱图数据（沿海）
  const floodDates = [...new Set(
    floodFocus.map((d) => dailyByDistrict[d] || []).flat().map((x) => x.date)
  )].sort()
  const floodData = floodDates.map((date) => {
    const row = { date }
    for (const name of floodFocus) {
      const hit = (dailyByDistrict[name] || []).find((x) => x.date === date)
      row[name] = hit ? hit.flood : null
    }
    return row
  })

  return (
    <div className="card cascade-panel">
      <div className="panel-title">
        🔗 多灾种链式预测 · 台风 → 降雨场 → 分区滑坡预警概率
        <span className="ml-sub">{ty.name} · {ty.n_track_points} 个路径点 · {ty.start} → {ty.end}</span>
      </div>
      <div className="cascade-chain">
        {(data.chain || []).map((c, i) => (
          <span key={i} className="chain-step">
            {i > 0 && <span className="chain-arrow">→</span>}
            {c}
          </span>
        ))}
      </div>

      <div className="cascade-subtitle">各区双灾种峰值：滑坡概率%（柱色）× 内涝深度 mm（标签）</div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={peaks.map((p) => ({ ...p, flood_mm: p.max_flood_depth_mm ?? 0 }))} layout="vertical" margin={{ left: 30 }}>
          <XAxis type="number" stroke="#9ab" unit="%" domain={[0, 100]} />
          <YAxis type="category" dataKey="district_name" stroke="#9ab" width={60} />
          <Tooltip
            contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }}
            formatter={(v, k, e) => {
              const p = e?.payload
              return [`${v}% 滑坡 · 内涝 ${p?.flood_mm ?? 0}mm · 日雨 ${p?.max_rain_24h}mm（${p?.peak_date}）`, '双灾种']
            }}
          />
          <Bar dataKey="peak_prob" radius={[0, 5, 5, 0]} label={{ position: 'right', fontSize: 10, fill: '#8fa3ba', formatter: (v) => `${(v * 100).toFixed(0)}%` }}>
            {peaks.map((p, i) => (
              <Cell key={i} fill={p.peak_prob >= 0.7 ? '#b3122b' : p.peak_prob >= 0.4 ? '#d6452a' : p.peak_prob >= 0.15 ? '#e08a1e' : '#c9b458'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className="grid-2col" style={{ padding: '0 14px' }}>
        {/* 滑坡支路日演进 */}
        <div>
          <div className="cascade-subtitle">⛰ 滑坡支路 · 山区概率日演进（%）</div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={slideData}>
              <XAxis dataKey="date" stroke="#9ab" />
              <YAxis stroke="#9ab" unit="%" domain={[0, 100]} />
              <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {focus.map((d, i) => (
                <Line key={d} type="monotone" dataKey={d} stroke={['#d6452a', '#e08a1e', '#c26b1e'][i % 3]} dot={false} strokeWidth={2} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* 内涝支路日演进 */}
        <div>
          <div className="cascade-subtitle">🌧️ 内涝支路 · 沿海积水深度日演进（mm，守恒模型）</div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={floodData}>
              <XAxis dataKey="date" stroke="#9ab" />
              <YAxis stroke="#9ab" unit="mm" />
              <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {floodFocus.map((d, i) => (
                <Line key={d} type="monotone" dataKey={d} stroke={['#4da3ff', '#37c8c3', '#9b6dff'][i % 3]} dot={false} strokeWidth={2} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="cascade-note">
        双灾种链路：{data.provenance}。滑坡概率来自 905 条官方预警训练的监督模型（时间外 AUC=0.813）；
        内涝深度来自守恒状态空间模型（真实 GIS 参数，质量守恒可审计）。降雨为台风路径参数化估计（非实测）。
      </div>
    </div>
  )
}
