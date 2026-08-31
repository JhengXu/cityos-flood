import { useEffect, useState } from 'react'
import { fetchJSON } from '../api'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts'

/**
 * SensitivityChart — 滑坡概率对降雨量的敏感性曲线（模型可解释性）
 */
const TIP = { background: 'var(--chart-tip-bg)', border: '1px solid var(--chart-tip-border)', borderRadius: 8, fontSize: 12, color: 'var(--ink)' }
const AXIS = { stroke: 'var(--chart-text)', fontSize: 11 }

export default function SensitivityChart({ sm1 = 0.35, month = 9 }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    fetchJSON(`/api/ml/landslide-sensitivity?rain_max_mm=200&sm1=${sm1}&month=${month}`)
      .then(setData).catch(() => setData(null))
  }, [sm1, month])

  if (!data?.curve) return null

  const chart = data.curve.map((p) => ({
    rain: p.rain_24h,
    概率: +(p.prob * 100).toFixed(1),
  }))

  // 找 50% 对应的降雨量
  const half = data.curve.find((p, i) => p.prob >= 0.5 && (i === 0 || data.curve[i-1].prob < 0.5))
  const threshold = half ? half.rain_24h : null

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="card-h">
        📈 滑坡概率 · 降雨敏感性曲线
        <span className="hint">
          {data.note} · 土壤湿度 {data.soil.sm1} · {data.month}月
        </span>
      </div>
      <div style={{ padding: '10px 12px', height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chart} margin={{ top: 8, right: 14, bottom: 0, left: -14 }}>
            <defs>
              <linearGradient id="gSens" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ff6b5e" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#ff6b5e" stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="rain" {...AXIS} unit="mm" tickLine={false} axisLine={false} />
            <YAxis {...AXIS} unit="%" domain={[0, 100]} tickLine={false} axisLine={false} width={44} />
            <Tooltip contentStyle={TIP} formatter={(v) => [`${v}%`, '预警概率']} labelFormatter={(l) => `24h 降雨 ${l}mm`} />
            <ReferenceLine y={50} stroke="var(--warn)" strokeDasharray="4 3" label={{ value: '50%', fontSize: 9, fill: 'var(--warn)' }} />
            {threshold != null && (
              <ReferenceLine x={threshold} stroke="var(--danger)" strokeDasharray="4 3"
                label={{ value: `临界 ~${threshold}mm`, fontSize: 9, fill: 'var(--danger)', position: 'top' }} />
            )}
            <Area dataKey="概率" type="monotone" stroke="#ff6b5e" strokeWidth={2.2} fill="url(#gSens)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div style={{ padding: '0 14px 10px' }}>
        <p className="footnote">
          {threshold != null
            ? `在本条件下，24h 降雨约 ${threshold}mm 时模型预警概率过半（临界值）。`
            : '当前条件下，扫描范围内概率未过半。'}
          诚实说明：单变量扫描中土壤湿度对临界值影响不显著（模型中 sm1 与
          前期降雨强交互）；真实决策需结合 rain_72h 累积（见艾云尼对照案例）。
        </p>
      </div>
    </div>
  )
}
