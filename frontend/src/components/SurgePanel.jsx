import { useEffect, useState } from 'react'
import { fetchJSON } from '../api'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid,
} from 'recharts'

/**
 * SurgePanel — 风暴潮实时预测面板
 * 天文潮谐波推算（HKO 8 分潮）+ 台风增水参数化叠加 + 预警水位分级
 * 数据来自 /api/surge/live
 */
const TIP = { background: 'var(--chart-tip-bg)', border: '1px solid var(--chart-tip-border)', borderRadius: 8, fontSize: 12, color: 'var(--ink)' }
const AXIS = { stroke: 'var(--chart-text)', fontSize: 11 }

export default function SurgePanel() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(0)

  useEffect(() => {
    fetchJSON('/api/surge/live?hours=48')
      .then(setData)
      .catch((e) => setErr(e.message))
  }, [])

  if (err) return <div className="err-box">⚠ {err}</div>
  if (!data) return <div className="card"><div className="loading">推算天文潮与增水…</div></div>

  const stations = data.stations || []
  if (!stations.length) return <div className="footnote">暂无潮位站数据</div>
  const st = stations[Math.min(sel, stations.length - 1)]

  // 图表数据：天文潮 + 总水位
  const chart = (st.series || []).map((r) => ({
    t: r.t.slice(5, 16).replace('T', ' '),
    天文潮: r.astro_m,
    总水位: r.total_m,
  }))
  // 预警阈值线
  const alertY = st.alert?.level >= 1 ? { 关注: 2.6, 警戒: 3.0, 严重: 3.5 } : null
  const thresholds = []
  if (chart.length) {
    if (st.alert?.level >= 1) thresholds.push({ y: 2.6, label: '关注 2.6m', color: '#fbbf24' })
    if (st.alert?.level >= 2) thresholds.push({ y: 3.0, label: '警戒 3.0m', color: '#ff6b5e' })
    if (st.alert?.level >= 3) thresholds.push({ y: 3.5, label: '严重 3.5m', color: '#ff4757' })
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="card-h">
        🌊 风暴潮 · 潮位推算与增水叠加
        <span className="hint">
          {data.typhoon
            ? `台风「${data.typhoon}」增水 +${data.surge_estimate_m.toFixed(2)}m`
            : '无活跃台风 · 仅天文潮'}
        </span>
      </div>

      {/* 站点选择 + 预警徽章 */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '10px 14px 0', flexWrap: 'wrap' }}>
        {stations.map((s, i) => (
          <button
            key={s.station_id}
            className={`chip ${i === sel ? 'on-selected' : ''}`}
            style={{
              cursor: 'pointer',
              borderColor: i === sel ? s.alert.color : undefined,
              background: i === sel ? `color-mix(in srgb, ${s.alert.color} 12%, transparent)` : undefined,
              color: i === sel ? s.alert.color : undefined,
            }}
            onClick={() => setSel(i)}
          >
            {s.name} · 峰值 {s.peak?.total_m?.toFixed(2) ?? '—'}m
          </button>
        ))}
        <span
          className="chip"
          style={{ color: st.alert.color, borderColor: `color-mix(in srgb, ${st.alert.color} 45%, transparent)` }}
        >
          {st.alert.name}
        </span>
        <span className="chip" style={{ marginLeft: 'auto' }}>谐波 RMSE {st.harmonic_rmse_m}m</span>
      </div>

      {/* 潮位曲线 */}
      <div style={{ flex: 1, padding: '8px 12px 10px', minHeight: 240 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chart} margin={{ top: 8, right: 14, bottom: 0, left: -10 }}>
            <defs>
              <linearGradient id="gTide" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2fd4c8" stopOpacity={0.32} />
                <stop offset="100%" stopColor="#2fd4c8" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="gTotal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ff6b5e" stopOpacity={0.28} />
                <stop offset="100%" stopColor="#ff6b5e" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="t" {...AXIS} tickLine={false} axisLine={false} minTickGap={48} />
            <YAxis {...AXIS} unit="m" domain={[0, 'auto']} tickLine={false} axisLine={false} width={44} />
            <Tooltip contentStyle={TIP} />
            {thresholds.map((th) => (
              <ReferenceLine
                key={th.y}
                y={th.y}
                stroke={th.color}
                strokeDasharray="5 4"
                label={{ value: th.label, fontSize: 9, fill: th.color, position: 'right' }}
              />
            ))}
            <Area dataKey="天文潮" type="monotone" stroke="#2fd4c8" strokeWidth={1.8} fill="url(#gTide)" />
            <Area dataKey="总水位" type="monotone" stroke="#ff6b5e" strokeWidth={2.2} fill="url(#gTotal)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* 说明 */}
      <div style={{ padding: '0 14px 12px' }}>
        <p className="footnote">
          {data.note} 基准 {st.datum}（海图基准）。
        </p>
        <p className="footnote">
          <b>数据来源：</b>天文潮 = HKO 3 年逐时数据拟合 8 分潮谐波（时间外验证 RMSE {st.harmonic_rmse_m}m）；
          增水 = 气压反效应 + 风堆积参数化（文献量级校准，非数值模式）。
          {data.disclaimer}
        </p>
      </div>
    </div>
  )
}
