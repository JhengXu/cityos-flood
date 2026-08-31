import { useEffect, useState, useMemo } from 'react'
import { getHazardsSummary } from '../api'
import SensitivityChart from './SensitivityChart.jsx'
import Scene3D from './Scene3D.jsx'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

/**
 * LandslidePage — 山体滑坡灾害页
 * 300 隐患点（坡度/坡高/易发性）+ 分区统计 + 预警史 + 3D 点位
 */
export default function LandslidePage() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [districtFilter, setDistrictFilter] = useState('全部')

  useEffect(() => {
    getHazardsSummary().then(setData).catch((e) => setErr(e.message))
  }, [])

  const ls = data?.landslide || {}
  const points = ls.points || []
  const districts = ls.districts || []
  const warnings = ls.warnings || {}

  const filtered = useMemo(
    () => (districtFilter === '全部' ? points : points.filter((p) => p.district === districtFilter)),
    [points, districtFilter]
  )

  const distChart = districts.map((d) => ({ name: d.district, n: d.n, high: d.n_high }))

  if (err) return <div className="card"><div className="err-box">⚠ {err}</div></div>
  if (!data) return <div className="card"><div className="loading">加载滑坡数据…</div></div>

  return (
    <div className="landslide-page">
      <div className="page-head">
        <h2>⛰ 山体滑坡灾害</h2>
        <p className="page-desc">
          深圳市规划和自然资源局官方 300 个地质灾害隐患点（坡高/坡度/等级，CGCS2000→WGS84 反算）。
          易发性评分 = 坡度(50%) + 坡高(30%) + 等级参数(20%)。
        </p>
      </div>

      {/* 预警统计卡片 */}
      <div className="hazard-cards">
        <div className="hazard-card landslide">
          <div className="hc-head">隐患点总数</div>
          <div className="hc-big">{ls.n}</div>
          <div className="hc-sub">高 {ls.n_high} · 中 {ls.n_mid} · 低 {ls.n_low}</div>
        </div>
        {Object.entries(warnings).filter(([k]) => k.includes('预警') && k !== '取消预警').map(([k, v]) => (
          <div key={k} className="hazard-card landslide">
            <div className="hc-head">{k}</div>
            <div className="hc-big" style={{ color: k.includes('红') ? '#b3122b' : k.includes('橙') ? '#d6452a' : '#c9b458' }}>{v}</div>
            <div className="hc-sub">历史发布次数</div>
          </div>
        ))}
      </div>

      {/* 分区统计图 */}
      <div className="card">
        <div className="panel-title">各分区隐患点数量（红色为高风险）</div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={distChart}>
            <XAxis dataKey="name" stroke="#9ab" angle={-35} textAnchor="end" height={60} />
            <YAxis stroke="#9ab" />
            <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
            <Bar dataKey="n" radius={[4, 4, 0, 0]}>
              {distChart.map((d, i) => (
                <Cell key={i} fill={d.high > 0 ? '#d6452a' : '#c26b1e'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* 3D 点位 */}
      <div className="card">
        <div className="map-title">滑坡隐患点 3D 空间分布（红=滑坡点，叠加地形与建筑）</div>
        <Scene3D height={460} showBuildings={false} />
      </div>

      {/* 隐患点明细表（可过滤） */}
      <div className="card">
        <div className="panel-title">
          隐患点明细（{filtered.length} 个）
          <select value={districtFilter} onChange={(e) => setDistrictFilter(e.target.value)} className="dist-select">
            <option value="全部">全部分区</option>
            {districts.map((d) => <option key={d.district} value={d.district}>{d.district}（{d.n}）</option>)}
          </select>
        </div>
        <div className="point-table-wrap">
          <table className="mini-table">
            <thead>
              <tr><th>分区</th><th>街道</th><th>位置</th><th>坡度</th><th>坡高</th><th>易发性</th><th>风险</th></tr>
            </thead>
            <tbody>
              {filtered.slice(0, 150).map((p, i) => (
                <tr key={i}>
                  <td>{p.district}</td>
                  <td>{p.street}</td>
                  <td className="td-site" title={p.site}>{p.site}</td>
                  <td>{p.slope_deg ?? '—'}°</td>
                  <td>{p.height_m ?? '—'}m</td>
                  <td><b>{p.susceptibility}</b></td>
                  <td><span style={{ color: p.risk_level >= 3 ? '#d6452a' : p.risk_level === 2 ? '#c9b458' : '#7ec8e3' }}>{p.risk_label}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length > 150 && <div className="footnote">仅显示前 150 条，共 {filtered.length} 条</div>}
        </div>
      </div>
      <SensitivityChart />
    </div>
  )
}
