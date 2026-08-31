import { useEffect, useState } from 'react'
import { getHazardsSummary } from '../api'
import Scene3D from './Scene3D.jsx'

/**
 * HazardOverview — 全自然灾害总览页
 * 四大灾种卡片 + 3D 城市场景
 */
export default function HazardOverview() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getHazardsSummary()
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="card"><div className="err-box">⚠ {error}</div></div>
  if (!data) return <div className="card"><div className="loading">加载四大灾种数据…</div></div>

  const ty = data.typhoon || {}
  const su = data.surge || {}
  const ls = data.landslide || {}

  const recentTyphoons = (ty.events || []).slice(-6).reverse()
  const topWave = (su.wave_events || []).slice().sort((a, b) => (b.max_swh_m || 0) - (a.max_swh_m || 0))
  const topSlide = (ls.districts || []).slice(0, 6)

  return (
    <div className="hazard-overview">
      {/* 四大灾种卡片 */}
      <div className="hazard-cards">
        <div className="hazard-card typhoon">
          <div className="hc-head"><span className="hc-icon">🌀</span>台风</div>
          <div className="hc-big">{ty.n ?? '—'}</div>
          <div className="hc-sub">历史影响事件（2014–2026）</div>
          <div className="hc-meta">
            {(ty.levels && Object.entries(ty.levels).map(([k, v]) => (
              <span key={k} className="hc-chip">{levelName(k)} {v}</span>
            ))) || null}
          </div>
          <div className="hc-src">{ty.source}</div>
        </div>

        <div className="hazard-card surge">
          <div className="hc-head"><span className="hc-icon">🌊</span>风暴潮</div>
          <div className="hc-big">{topWave[0] ? `${topWave[0].max_swh_m}m` : '—'}</div>
          <div className="hc-sub">历史最大波高（{topWave[0]?.event_name || ''}）</div>
          <div className="hc-meta">
            {(su.stations || []).map((s) => (
              <span key={s.station_id} className="hc-chip">{s.name} 潮差{s.tidal_range_m}m</span>
            ))}
          </div>
          <div className="hc-src">{su.source}</div>
        </div>

        <div className="hazard-card flood">
          <div className="hc-head"><span className="hc-icon">🌧️</span>内涝</div>
          <div className="hc-big">守恒集合</div>
          <div className="hc-sub">状态空间模型 · 64成员 · P10/P50/P90</div>
          <div className="hc-meta">
            <span className="hc-chip">10区·逐时</span>
            <span className="hc-chip">观测同化</span>
            <span className="hc-chip">反事实推演</span>
          </div>
          <div className="hc-src">{data.flood?.provenance}</div>
        </div>

        <div className="hazard-card landslide">
          <div className="hc-head"><span className="hc-icon">⛰</span>山体滑坡</div>
          <div className="hc-big">{ls.n ?? '—'}</div>
          <div className="hc-sub">官方隐患点（含坡度/坡高）</div>
          <div className="hc-meta">
            <span className="hc-chip">高风险 {ls.n_high ?? 0}</span>
            <span className="hc-chip">中风险 {ls.n_mid ?? 0}</span>
            {ls.warnings ? <span className="hc-chip">预警 {Object.values(ls.warnings).reduce((a, b) => a + b, 0)} 条</span> : null}
          </div>
          <div className="hc-src">{ls.source}</div>
        </div>
      </div>

      {/* 3D 城市场景 */}
      <div className="card">
        <div className="map-title">深圳 3D 城市实景 · 地形 + 建筑 + 四大灾种点位</div>
        <Scene3D height={520} />
      </div>

      {/* 最近台风 + 滑坡分区 */}
      <div className="grid-2col">
        <div className="card">
          <div className="panel-title">最近影响深圳的台风</div>
          <table className="mini-table">
            <thead><tr><th>名称</th><th>年份</th><th>强度</th><th>最近距离</th></tr></thead>
            <tbody>
              {recentTyphoons.map((e) => (
                <tr key={e.sid}>
                  <td>{e.name || e.sid}</td>
                  <td>{e.season}</td>
                  <td><span className="lvl-tag" style={{ color: levelColor(e.level) }}>{e.level_label}</span></td>
                  <td>{e.min_dist_km} km</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="panel-title">滑坡隐患分区 TOP</div>
          <table className="mini-table">
            <thead><tr><th>区</th><th>隐患点</th><th>高风险</th><th>最大易发性</th></tr></thead>
            <tbody>
              {topSlide.map((d) => (
                <tr key={d.district}>
                  <td>{d.district}</td>
                  <td>{d.n}</td>
                  <td>{d.n_high}</td>
                  <td>{d.max_susceptibility}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function levelName(k) {
  return { super_typhoon: '超强', severe_typhoon: '强', typhoon: '台风', sts: '强热带风暴', ts: '热带风暴', td: '低压', unknown: '未知' }[k] || k
}
function levelColor(k) {
  return { super_typhoon: '#b3122b', severe_typhoon: '#d6452a', typhoon: '#e08a1e', sts: '#c9b458', ts: '#7ec8e3', td: '#a8d5ba', unknown: '#888' }[k] || '#888'
}
