import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, Popup } from 'react-leaflet'
import { getStreetRisk } from '../api'
import { formatDepthM, levelColor } from '../api'

const CENTER = [22.5431, 114.0579]
const depthLevel = (depthM = 0) => depthM >= 0.5 ? 4 : depthM >= 0.3 ? 3 : depthM >= 0.15 ? 2 : depthM >= 0.05 ? 1 : 0

export default function StreetRiskPanel({ forecastDays = 3, forecastRunId = null }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    let active = true
    getStreetRisk(forecastDays, forecastRunId)
      .then((result) => {
        if (active && (!forecastRunId || result.forecast_run_id === forecastRunId)) setData(result)
      })
      .catch(() => { if (active) setData(null) })
    return () => { active = false }
  }, [forecastDays, forecastRunId])

  if (!data) return null
  const streets = data.streets || []

  return (
    <section className="card stage">
      <div className="card-h">
        街道级内涝风险 · 真实 GIS 特征
        <span className="hint">区级守恒集合 + 30 个真实 DEM/WorldCover 采样点的有界下尺度 · 数据源 {data.source}</span>
      </div>
      <div className="rd-grid">
        <div className="rd-map">
          <div className="realmap">
            <MapContainer center={CENTER} zoom={11} className="map" scrollWheelZoom={false}>
              <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution="© OpenStreetMap © CARTO" />
              {streets.map((s, i) => (
                <CircleMarker key={i} center={[s.lat, s.lon]} radius={5 + s.vulnerability * 8}
                  pathOptions={{ color: levelColor(depthLevel(s.peak_depth_p50_m)), fillColor: levelColor(depthLevel(s.peak_depth_p50_m)), fillOpacity: .7, weight: 2 }}>
                  <Tooltip direction="top">{s.name}</Tooltip>
                  <Popup>
                    <div className="pop-h">{s.name} · {s.district_id}</div>
                    <div className="pop-row"><span>脆弱性</span><span>{(s.vulnerability * 100).toFixed(0)}%</span></div>
                    <div className="pop-row"><span>高程(真实)</span><span>{s.elevation}m</span></div>
                    <div className="pop-row"><span>不透水(真实)</span><span>{Math.round(s.impervious * 100)}%</span></div>
                    <div className="pop-row"><span>峰值 P50 / P90</span><b style={{ color: levelColor(depthLevel(s.peak_depth_p50_m)) }}>{formatDepthM(s.peak_depth_p50_m)} / {formatDepthM(s.peak_depth_p90_m)}</b></div>
                    <div className="pop-row" title={s.peak_probability_definition}><span>全期任一时刻≥15cm</span><span>{(s.peak * 100).toFixed(0)}%</span></div>
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
          <div className="wm-h">街道采样点排行（按 P50 峰值水深）</div>
          <div className="pf-table">
            <div className="pf-head"><span>街道</span><span>区</span><span>P50峰深</span><span>全期≥15cm</span><span>高程</span><span>不透水</span></div>
            {streets.slice(0, 12).map((s, i) => (
              <div className="pf-row" key={i}>
                <span className="pf-name">{s.name}</span>
                <span>{s.district_id}</span>
                <span className={s.peak_depth_p50_m >= 0.3 ? 'hot' : ''}>{formatDepthM(s.peak_depth_p50_m)}</span>
                <span>{Math.round(s.peak * 100)}%</span>
                <span>{s.elevation}m</span>
                <span>{Math.round(s.impervious * 100)}%</span>
              </div>
            ))}
          </div>
          <div className="mc-note">这是区级集合水深按真实 DEM 高程和 WorldCover 不透水率做的 0.60–1.65 有界排序因子，不是街道级二维水动力结果。接入管网拓扑、道路高程与高分辨率雷达后才能提高空间精度。</div>
        </div>
      </div>
    </section>
  )
}
