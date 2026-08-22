import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts'
import { fmtTime, levelColor } from '../api'

export default function SimulateChart({ sim, selected, onSelect }) {
  if (!sim) return <div className="card chart-card">选择上方情景后查看推演曲线</div>
  const districts = sim.districts
  const sel = districts.find((d) => d.id === selected) || districts[0]
  const data = sim.times.map((t, i) => ({
    t: fmtTime(t),
    base: Math.round(sel.base_prob[i] * 100),
    scen: Math.round(sel.scenario_prob[i] * 100),
  }))

  return (
    <div className="card chart-card">
      <div className="card-h">
        内涝风险推演轨迹
        <select
          value={sel.id}
          onChange={(e) => onSelect(e.target.value)}
          className="dist-select"
        >
          {districts.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="rgba(255,255,255,.06)" />
          <XAxis
            dataKey="t"
            tick={{ fill: '#8C9098', fontSize: 10 }}
            interval={Math.max(0, Math.floor(data.length / 8) - 1)}
          />
          <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={[0, 100]} unit="%" />
          <Tooltip
            contentStyle={{
              background: '#0B0D10',
              border: '1px solid rgba(255,255,255,.12)',
              color: '#F3F3EF',
            }}
          />
          <Legend />
          <Line type="monotone" dataKey="base" name="基线" stroke="#5C6067" dot={false} />
          <Line
            type="monotone"
            dataKey="scen"
            name="情景"
            stroke="#145BFF"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="sim-note">
        峰值：基线 <b>{sel.base_peak.level_label}</b> → 情景{' '}
        <b style={{ color: levelColor(sel.scenario_peak.level) }}>
          {sel.scenario_peak.level_label}
        </b>{' '}
        （{fmtTime(sel.scenario_peak.time)}，概率 {(sel.scenario_peak.prob * 100).toFixed(0)}%）
      </div>
    </div>
  )
}
