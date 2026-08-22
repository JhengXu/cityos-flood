import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  ReferenceDot,
} from 'recharts'
import { fmtTime, levelColor } from '../api'

export default function RainfallChart({ data, hour, setHour }) {
  const chart = data.hours.map((h, i) => ({
    t: fmtTime(h),
    precip: data.rainfall[i],
  }))
  const sel = chart[Math.min(hour, chart.length - 1)]
  return (
    <div className="card chart-card">
      <div className="card-h">
        深圳小时降雨预报
        <span className="hint">虚线 = 全市排水设计均值 {data.drainage_avg} mm/h</span>
      </div>
      <ResponsiveContainer width="100%" height={190}>
        <LineChart
          data={chart}
          margin={{ top: 8, right: 12, bottom: 0, left: -18 }}
          onClick={(e) => {
            if (e && e.activeTooltipIndex != null) setHour(e.activeTooltipIndex)
          }}
        >
          <CartesianGrid stroke="rgba(255,255,255,.06)" />
          <XAxis
            dataKey="t"
            tick={{ fill: '#8C9098', fontSize: 10 }}
            interval={Math.max(0, Math.floor(chart.length / 8) - 1)}
          />
          <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} />
          <Tooltip
            contentStyle={{
              background: '#0B0D10',
              border: '1px solid rgba(255,255,255,.12)',
              color: '#F3F3EF',
            }}
            formatter={(v) => [`${v} mm`, '降雨']}
          />
          <ReferenceLine y={data.drainage_avg} stroke="#FF6A1F" strokeDasharray="4 4" />
          {sel && (
            <ReferenceLine x={sel.t} stroke="#145BFF" strokeWidth={2} />
          )}
          <Line
            type="monotone"
            dataKey="precip"
            stroke="#145BFF"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
          {sel && (
            <ReferenceDot x={sel.t} y={sel.precip} r={5} fill={levelColor(0)} stroke="#fff" />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
