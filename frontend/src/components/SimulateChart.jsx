import {
  ResponsiveContainer,
  LineChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts'
import { fmtTime, levelColor, formatDepthM, formatPercent } from '../api'

export default function SimulateChart({ sim, selected, onSelect }) {
  if (!sim) return <div className="card chart-card">选择上方情景后查看推演曲线</div>
  const districts = sim.districts || []
  if (!districts.length) return <div className="card chart-card">当前情景没有可用的分区轨迹</div>
  const sel = districts.find((d) => d.id === selected) || districts[0]
  const hasDepth = Array.isArray(sel.scenario_depth_p50_m)
  const data = sim.times.map((t, i) => ({
    t: fmtTime(t),
    base: hasDepth
      ? (sel.base_depth_p50_m?.[i] ?? null)
      : Math.round((sel.base_prob?.[i] || 0) * 100),
    scen: hasDepth
      ? (sel.scenario_depth_p50_m[i] ?? null)
      : Math.round((sel.scenario_prob?.[i] || 0) * 100),
    scenRange: hasDepth ? [sel.scenario_depth_p10_m?.[i] ?? 0, sel.scenario_depth_p90_m?.[i] ?? 0] : null,
  }))

  return (
    <div className="card chart-card">
      <div className="card-h">
        {hasDepth ? '积水水深集合推演' : '内涝概率推演（兼容口径）'}
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
          <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={hasDepth ? ['auto', 'auto'] : [0, 100]} unit={hasDepth ? 'm' : '%'} />
          <Tooltip
            contentStyle={{
              background: '#0B0D10',
              border: '1px solid rgba(255,255,255,.12)',
              color: '#F3F3EF',
            }}
          />
          <Legend />
          {hasDepth && <Area type="monotone" dataKey="scenRange" name="情景 P10–P90" stroke="none" fill="rgba(20,91,255,.16)" />}
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
        峰值：基线 <b>{sel.base_peak?.depth_p50_m != null ? formatDepthM(sel.base_peak.depth_p50_m) : sel.base_peak?.level_label}</b> → 情景{' '}
        <b style={{ color: levelColor(sel.scenario_peak?.level) }}>
          {sel.scenario_peak?.depth_p50_m != null ? formatDepthM(sel.scenario_peak.depth_p50_m) : sel.scenario_peak?.level_label}
        </b>{' '}
        （{fmtTime(sel.scenario_peak?.time)}，P(水深≥15cm) {formatPercent(sel.scenario_peak?.prob)}）
        {sim.simulation_run_id && <span> · run {sim.simulation_run_id.slice(0, 10)}</span>}
      </div>
    </div>
  )
}
