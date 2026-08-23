import {
  ResponsiveContainer, AreaChart, Area, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, Legend, ReferenceLine,
} from 'recharts'
import { fmtTime } from '../api'

export default function OceanBoundaryPanel({ sim }) {
  const ocean = sim?.ocean
  if (!ocean) return <section className="card stage ocean-card"><div className="empty">正在计算海洋边界条件…</div></section>

  const rows = ocean.times.map((time, i) => ({
    time: fmtTime(time),
    astronomical: ocean.astronomical_tide_m[i],
    surge: ocean.storm_surge_m[i],
    total: ocean.total_level_m[i],
  }))
  const offset = ocean.rain_tide_peak_offset_h
  const compound = Math.round((ocean.compound_index || 0) * 100)
  const affected = [...(sim?.districts || [])].sort((a, b) => a.min_drainage_factor - b.min_drainage_factor).slice(0, 4)

  return (
    <section className="card stage ocean-card">
      <div className="card-h">
        海洋边界条件 · 复合内涝
        <span className="hint">天文潮 + 风暴增水 → 沿海排水受限 → 与降雨峰值耦合</span>
        <span className="prov-pill">{!ocean.station || ocean.station.quality === 'unavailable' ? '物理代理 · 待潮位站校准' : `站点 ${ocean.station.id}`}</span>
      </div>
      <div className="ocean-kpis">
        <div className="ov-card"><div className="ov-k">海面峰值</div><div className="ov-v">{ocean.peak.total_level_m}m</div><div className="ov-sub">{fmtTime(ocean.peak.time)}</div></div>
        <div className="ov-card"><div className="ov-k">峰值增水</div><div className="ov-v">{ocean.peak.surge_m}m</div><div className="ov-sub">参数化风暴增水</div></div>
        <div className="ov-card"><div className="ov-k">雨峰−潮峰</div><div className="ov-v">{offset == null ? '—' : `${offset > 0 ? '+' : ''}${offset}h`}</div><div className="ov-sub">0h 表示峰值重合</div></div>
        <div className="ov-card"><div className="ov-k">复合强度指数</div><div className="ov-v">{compound}</div><div className="ov-sub">仅用于情景比较</div></div>
        <div className="ov-card"><div className="ov-k">距下次高潮</div><div className="ov-v">{ocean.time_to_next_high_tide_h?.[0] ?? '—'}h</div><div className="ov-sub">当前潮相 {ocean.tide_phase?.[0] || '—'}</div></div>
      </div>
      <div className="ocean-grid">
        <div className="ocean-chart">
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={rows} margin={{ top: 8, right: 14, bottom: 0, left: -10 }}>
              <CartesianGrid stroke="rgba(255,255,255,.06)" />
              <XAxis dataKey="time" tick={{ fill: '#8C9098', fontSize: 10 }} interval={Math.max(1, Math.floor(rows.length / 8))} />
              <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} unit="m" />
              <Tooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
              <Legend />
              <ReferenceLine y={0} stroke="rgba(255,255,255,.25)" />
              <Area dataKey="surge" name="风暴增水" fill="rgba(214,69,42,.18)" stroke="#d6452a" />
              <Line dataKey="astronomical" name="天文潮" stroke="#8C9098" dot={false} strokeWidth={1.5} />
              <Line dataKey="total" name="总海面" stroke="#145BFF" dot={false} strokeWidth={2.4} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="ocean-explain">
          <div className="wm-h">模型如何影响城市</div>
          <div className="ocean-flow"><span>海面升高</span><i>→</i><span>排水口水头差下降</span><i>→</i><span>沿海排水能力降低</span><i>→</i><span>积水风险上升</span></div>
          <div className="wm-h">数据可信边界</div>
          <div className="prov-line"><b>天文潮</b><span>{ocean.provenance.astronomical_tide}</span></div>
          <div className="prov-line"><b>风暴增水</b><span>{ocean.provenance.storm_surge}</span></div>
          <div className="prov-line"><b>排水耦合</b><span>{ocean.provenance.drainage_coupling}</span></div>
          <div className="ocean-warning">⚠ {ocean.warning}</div>
          <div className="wm-h">受潮位顶托影响最大</div>
          {affected.map((d) => <div className="prov-line" key={d.id}><b>{d.name}</b><span>最低排水系数 {Math.round(d.min_drainage_factor * 100)}% · {d.ocean_boundary?.boundary}</span></div>)}
          <div className="wm-h">站点与质量</div>
          <div className="prov-line"><b>站点/基准面</b><span>{ocean.station?.id || '尚未接入'} / {ocean.station?.datum || '不可用'}</span></div>
          <div className="prov-line"><b>更新时间</b><span>{ocean.station?.updated_at || '—'}</span></div>
          <div className="prov-line"><b>不确定性</b><span>{ocean.uncertainty?.level} · {ocean.uncertainty?.reason}</span></div>
          <div className="prov-line"><b>向岸风/气压异常</b><span>{ocean.onshore_wind_component_m_s ?? '待接入'} m/s · {ocean.pressure_anomaly_hpa ?? '待接入'} hPa</span></div>
        </div>
      </div>
    </section>
  )
}
