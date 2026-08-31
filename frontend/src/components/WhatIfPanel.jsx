import { useEffect, useState } from 'react'
import { fetchJSON } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts'

/**
 * WhatIfPanel — 台风情景推演（路径平移/强度缩放 → 灾害链对比）
 * 数据来自 /api/cascade/whatif
 */
const TIP = { background: 'var(--chart-tip-bg)', border: '1px solid var(--chart-tip-border)', borderRadius: 8, fontSize: 12, color: 'var(--ink)' }
const AXIS = { stroke: 'var(--chart-text)', fontSize: 11 }

const PRESETS = [
  { label: '路径靠近 50km', dist: -50, wind: 1.0 },
  { label: '路径靠近 100km', dist: -100, wind: 1.0 },
  { label: '路径远离 50km', dist: 50, wind: 1.0 },
  { label: '强度 +20%', dist: 0, wind: 1.2 },
  { label: '强度 +20% 且靠近 50km', dist: -50, wind: 1.2 },
  { label: '强度 -20%', dist: 0, wind: 0.8 },
]

export default function WhatIfPanel({ typhoonName }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dist, setDist] = useState(-100)
  const [wind, setWind] = useState(1.0)
  const [name, setName] = useState(typhoonName || '')

  async function run(d = dist, w = wind, n = name) {
    setBusy(true)
    try {
      const params = new URLSearchParams({ dist_shift_km: d, wind_factor: w })
      if (n) params.set('name', n)
      const r = await fetchJSON(`/api/cascade/whatif?${params}`)
      setData(r)
    } catch (e) {
      setData({ error: e.message })
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    // 默认用活跃台风
    fetchJSON('/api/live').then((d) => {
      const ty = d?.typhoon_now?.name
      if (ty) { setName(ty); run(-100, 1.0, ty) }
      else run(-100, 1.0, '')
    }).catch(() => {})
  }, [])

  const applyPreset = (p) => {
    setDist(p.dist); setWind(p.wind)
    run(p.dist, p.wind, name)
  }

  // 多情景对比（并行跑 3 个关键预设）
  const [compare, setCompare] = useState(null)
  async function runCompare() {
    setBusy(true)
    try {
      const scenarios = [
        { label: '基准（实际路径）', dist: 0, wind: 1.0 },
        { label: '路径靠近 100km', dist: -100, wind: 1.0 },
        { label: '强度 +20% 且靠近 50km', dist: -50, wind: 1.2 },
      ]
      const results = await Promise.all(scenarios.map(async (s) => {
        const params = new URLSearchParams({ dist_shift_km: s.dist, wind_factor: s.wind })
        if (name) params.set('name', name)
        const r = await fetchJSON(`/api/cascade/whatif?${params}`)
        return { ...s, r }
      }))
      setCompare(results)
    } catch (e) {
      setCompare({ error: e.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="card-h">
        🌀 台风情景 What-if 推演
        <span className="hint">{name ? `当前台风：${name}` : '无活跃台风'} · 路径平移与强度缩放 → 灾害链重算</span>
      </div>

      <div style={{ padding: '10px 14px', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {PRESETS.map((p) => (
          <button key={p.label} className="btn sm" onClick={() => applyPreset(p)} disabled={busy}
            style={dist === p.dist && wind === p.wind ? { borderColor: 'var(--accent)', color: 'var(--accent)' } : {}}>
            {p.label}
          </button>
        ))}
        <button className="btn sm primary" onClick={() => run()} disabled={busy}>
          {busy ? '推演中…' : `自定义推演（${dist > 0 ? '+' : ''}${dist}km / ×${wind}）`}
        </button>
        <button className="btn sm" onClick={runCompare} disabled={busy} style={{ marginLeft: 'auto' }}>
          {busy ? '计算中…' : '📊 三情景对比'}
        </button>
      </div>

      {compare && !compare.error && (
        <div style={{ padding: '0 14px 10px', overflowX: 'auto' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink-2)', marginBottom: 6 }}>多情景对比</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--line)' }}>
                <th style={{ textAlign: 'left', padding: '5px 8px', color: 'var(--ink-3)' }}>情景</th>
                <th style={{ textAlign: 'right', padding: '5px 8px', color: 'var(--ink-3)' }}>最近距离</th>
                <th style={{ textAlign: 'right', padding: '5px 8px', color: 'var(--ink-3)' }}>最大日雨</th>
                <th style={{ textAlign: 'right', padding: '5px 8px', color: 'var(--ink-3)' }}>滑坡概率</th>
                <th style={{ textAlign: 'right', padding: '5px 8px', color: 'var(--ink-3)' }}>内涝峰值</th>
              </tr>
            </thead>
            <tbody>
              {compare.map((s, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--line-soft)' }}>
                  <td style={{ padding: '5px 8px', fontWeight: 600 }}>{s.label}</td>
                  <td className="mono" style={{ textAlign: 'right', padding: '5px 8px' }}>{s.r.whatif.min_dist_km}km</td>
                  <td className="mono" style={{ textAlign: 'right', padding: '5px 8px' }}>{s.r.whatif.max_rain}mm</td>
                  <td className="mono" style={{ textAlign: 'right', padding: '5px 8px', color: s.r.whatif.max_prob >= 0.4 ? 'var(--danger)' : 'inherit' }}>
                    {(s.r.whatif.max_prob * 100).toFixed(0)}%
                  </td>
                  <td className="mono" style={{ textAlign: 'right', padding: '5px 8px' }}>{s.r.whatif.max_flood}mm</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data?.error && <div className="err-box" style={{ margin: '0 14px 12px' }}>⚠ {data.error}</div>}

      {data && !data.error && (
        <div style={{ padding: '0 14px 14px' }}>
          {/* 对比表 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginBottom: 12 }}>
            <Metric label="最近距离" base={data.baseline.min_dist_km} whatif={data.whatif.min_dist_km} unit="km" />
            <Metric label="最大日降雨" base={data.baseline.max_rain} whatif={data.whatif.max_rain} unit="mm" />
            <Metric label="滑坡预警概率" base={data.baseline.max_prob * 100} whatif={data.whatif.max_prob * 100} unit="%" fmt={(v) => v.toFixed(1)} />
            <Metric label="内涝峰值" base={data.baseline.max_flood} whatif={data.whatif.max_flood} unit="mm" />
            <Metric label="预警日数(≥40%)" base={data.baseline.n_alert_days} whatif={data.whatif.n_alert_days} unit="天" />
            {data.surge?.baseline_m != null && (
              <Metric label="台风增水" base={data.surge.baseline_m} whatif={data.surge.whatif_m} unit="m" fmt={(v) => v.toFixed(2)} />
            )}
          </div>

          {/* 日序列对比图 */}
          {data.baseline_daily?.length > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink-2)', marginBottom: 4 }}>滑坡概率日演进：基准 vs 情景</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={data.baseline_daily.map((b, i) => ({
                    date: b.date?.slice(5) || `D${i}`,
                    基准: +(b.landslide_warning_prob * 100).toFixed(1),
                    情景: +((data.whatif_daily?.[i]?.landslide_warning_prob ?? 0) * 100).toFixed(1),
                  }))}
                  margin={{ top: 4, right: 12, bottom: 0, left: -16 }}
                >
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" {...AXIS} tickLine={false} axisLine={false} />
                  <YAxis {...AXIS} unit="%" tickLine={false} axisLine={false} width={48} />
                  <Tooltip contentStyle={TIP} cursor={{ fill: 'var(--line-soft)' }} />
                  <ReferenceLine y={40} stroke="var(--warn)" strokeDasharray="4 3" label={{ value: '预警线', fontSize: 9, fill: 'var(--warn)' }} />
                  <Bar dataKey="基准" fill="#5b7ba8" radius={[3, 3, 0, 0]} barSize={14} />
                  <Bar dataKey="情景" fill="#ff6b5e" radius={[3, 3, 0, 0]} barSize={14} />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}

          <p className="footnote" style={{ marginTop: 8 }}>
            {data.note} 数据链：{data.provenance}
          </p>
        </div>
      )}
    </div>
  )
}


function Metric({ label, base, whatif, unit, fmt }) {
  const d = whatif - base
  const up = d > 0
  const color = Math.abs(d) < 0.05 ? 'var(--ink-3)' : up ? 'var(--danger)' : 'var(--ok)'
  const f = fmt || ((v) => Number.isInteger(v) ? v : v.toFixed(1))
  return (
    <div style={{ padding: '8px 10px', background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 9 }}>
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600 }}>
        <span style={{ color: 'var(--ink-4)' }}>{f(base)}</span>
        <span style={{ margin: '0 4px', color: 'var(--ink-4)' }}>→</span>
        <span>{f(whatif)}{unit}</span>
      </div>
      <div style={{ fontSize: 10, color, fontWeight: 600, marginTop: 2 }}>
        {Math.abs(d) < 0.05 ? '无变化' : `${up ? '↑' : '↓'} ${f(Math.abs(d))}${unit}`}
      </div>
    </div>
  )
}
