import { useEffect, useState } from 'react'
import { getHazardsSummary, getTyphoonTrack } from '../api'
import Scene3D from './Scene3D.jsx'
import CascadePanel from './CascadePanel.jsx'
import WhatIfPanel from './WhatIfPanel.jsx'

/**
 * TyphoonPage — 台风灾害页
 * 历史影响台风事件表 + 台风路径选择 + 3D 路径叠加 + 路径详情
 */
export default function TyphoonPage() {
  const [summary, setSummary] = useState(null)
  const [selected, setSelected] = useState(null)  // {name, sid}
  const [track, setTrack] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    getHazardsSummary().then((d) => {
      setSummary(d)
      // 默认选最近的超强台风：RAGASA 或最新的
      const evs = (d.typhoon?.events || []).filter((e) => e.level === 'super_typhoon')
      const pick = evs.length ? evs[evs.length - 1] : (d.typhoon?.events || [])[(d.typhoon?.events?.length || 1) - 1]
      if (pick) setSelected({ name: pick.name, sid: pick.sid })
    }).catch((e) => setErr(e.message))
  }, [])

  useEffect(() => {
    if (!selected) return
    setTrack(null)
    getTyphoonTrack(selected.name, selected.sid)
      .then((d) => setTrack(d.points || []))
      .catch(() => setTrack([]))
  }, [selected])

  if (err) return <div className="card"><div className="err-box">⚠ {err}</div></div>

  const events = summary?.typhoon?.events || []
  const selEvent = events.find((e) => e.sid === selected?.sid)

  return (
    <div className="typhoon-page">
      <div className="page-head">
        <h2>🌀 台风灾害</h2>
        <p className="page-desc">
          基于 IBTrACS 最佳路径数据集（2014–2026），共 {events.length} 个历史影响深圳的台风（路径距深圳 &lt;300km）。
          选择台风查看 3D 路径与详细信息。
        </p>
      </div>

      <div className="grid-2col">
        {/* 台风事件列表 */}
        <div className="card">
          <div className="panel-title">影响深圳的台风（点击查看路径）</div>
          <div className="typhoon-list">
            {events.slice().reverse().map((e) => (
              <button
                key={e.sid}
                className={`typhoon-item ${selected?.sid === e.sid ? 'on' : ''}`}
                onClick={() => setSelected({ name: e.name, sid: e.sid })}
              >
                <span className="ti-name">{e.name || e.sid}</span>
                <span className="ti-year">{e.season}</span>
                <span className="ti-level" style={{ color: lvlColor(e.level) }}>{e.level_label}</span>
                <span className="ti-dist">{e.min_dist_km}km</span>
              </button>
            ))}
          </div>
        </div>

        {/* 选中台风详情 */}
        <div className="card">
          <div className="panel-title">
            {selEvent ? `${selEvent.name || selEvent.sid}（${selEvent.season}）· ${selEvent.level_label}` : '选择台风查看详情'}
          </div>
          {selEvent && (
            <div className="typhoon-detail">
              <div className="td-row"><span>最近距离</span><b>{selEvent.min_dist_km} km</b></div>
              <div className="td-row"><span>最近时刻中心</span><b>{selEvent.closest_lat}°N, {selEvent.closest_lon}°E</b></div>
              <div className="td-row"><span>峰值风速</span><b>{selEvent.peak_wind_kt ?? '—'} kt</b></div>
              <div className="td-row"><span>最低气压</span><b>{selEvent.min_pres_hpa ?? '—'} hPa</b></div>
              <div className="td-row"><span>最近时刻</span><b>{selEvent.closest_time}</b></div>
              {track && track.length > 0 && (
                <div className="td-track">
                  <div className="td-sub">路径点（{track.length} 个，末 8 点）</div>
                  {track.slice(-8).map((p, i) => (
                    <div key={i} className="td-row">
                      <span>{String(p.time).slice(5, 16)}</span>
                      <b>{p.lat}°N {p.lon}°E {p.wind_kt ? `${p.wind_kt}kt` : ''}</b>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 3D 路径场景 */}
      <div className="card">
        <div className="map-title">
          台风 3D 路径 · {selEvent ? `${selEvent.name || selEvent.sid}（${selEvent.season}）` : ''}
        </div>
        {selected ? <Scene3D height={480} typhoonTrack={track} /> : <Scene3D height={480} />}
      </div>

      {/* 多灾种链式预测：台风 → 降雨 → 滑坡 */}
      {selected && <CascadePanel selected={selected} />}
      <WhatIfPanel typhoonName={selected?.name} />
    </div>
  )
}

function lvlColor(k) {
  return { super_typhoon: '#b3122b', severe_typhoon: '#d6452a', typhoon: '#e08a1e', sts: '#c9b458', ts: '#7ec8e3', td: '#a8d5ba', unknown: '#888' }[k] || '#888'
}
