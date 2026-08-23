import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, Popup } from 'react-leaflet'
import { getStreetRisk } from '../api'
import { levelColor, LEVEL_LABELS } from '../api'

const CENTER = [22.5431, 114.0579]

export default function StreetRiskPanel() {
  const [data, setData] = useState(null)
  useEffect(() => { getStreetRisk(2).then(setData).catch(() => setData(null)) }, [])

  if (!data) return null
  const streets = data.streets || []

  return (
    <section className="card stage">
      <div className="card-h">
        街道级内涝风险 · 真实 GIS 特征
        <span className="hint">30 个街道采样点 · 真实 DEM 高程 + WorldCover 不透水 + 街道降雨 · 数据源 {data.source}</span>
      </div>
      <div className="rd-grid">
        <div className="rd-map">
          <div className="realmap">
            <MapContainer center={CENTER} zoom={11} className="map" scrollWheelZoom={false}>
              <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution="© OpenStreetMap © CARTO" />
              {streets.map((s, i) => (
                <CircleMarker key={i} center={[s.lat, s.lon]} radius={5 + s.vulnerability * 8}
                  pathOptions={{ color: levelColor(Math.round(s.peak * 4)), fillColor: levelColor(Math.round(s.peak * 4)), fillOpacity: .7, weight: 2 }}>
                  <Tooltip direction="top">{s.name}</Tooltip>
                  <Popup>
                    <div className="pop-h">{s.name} · {s.district_id}</div>
                    <div className="pop-row"><span>脆弱性</span><span>{(s.vulnerability * 100).toFixed(0)}%</span></div>
                    <div className="pop-row"><span>高程(真实)</span><span>{s.elevation}m</span></div>
                    <div className="pop-row"><span>不透水(真实)</span><span>{Math.round(s.impervious * 100)}%</span></div>
                    <div className="pop-row"><span>峰值风险</span><b style={{ color: levelColor(Math.round(s.peak * 4)) }}>{s.peak.toFixed(2)}</b></div>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>
          <div className="rd-legend">
            <i style={{ background: '#1f7a4d' }} />低　<i style={{ background: '#c9b458' }} />中　<i style={{ background: '#e08a1e' }} />高　<i style={{ background: '#d6452a' }} />极高　· 半径=街道脆弱性
          </div>
        </div>

        <div className="rd-cell">
          <div className="wm-h">街道风险排行（按峰值）</div>
          <div className="pf-table">
            <div className="pf-head"><span>街道</span><span>区</span><span>峰值</span><span>脆弱</span><span>高程</span><span>不透水</span></div>
            {streets.slice(0, 12).map((s, i) => (
              <div className="pf-row" key={i}>
                <span className="pf-name">{s.name}</span>
                <span>{s.district_id}</span>
                <span className={s.peak > 0.65 ? 'hot' : ''}>{s.peak.toFixed(2)}</span>
                <span>{Math.round(s.vulnerability * 100)}%</span>
                <span>{s.elevation}m</span>
                <span>{Math.round(s.impervious * 100)}%</span>
              </div>
            ))}
          </div>
          <div className="mc-note">街道特征由真实 DEM(高程) + WorldCover(不透水) 计算；街道降雨来自多点 Open-Meteo 采样点。精度为街道采样点级（30 个），接入权威街道管网/下垫面后可进一步细分。</div>
        </div>
      </div>
    </section>
  )
}
