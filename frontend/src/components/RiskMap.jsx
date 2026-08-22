import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip } from 'react-leaflet'
import { fmtTime, levelColor, LEVEL_LABELS } from '../api'

export default function RiskMap({ data, view }) {
  const center = data.city.center
  return (
    <div className="map-wrap">
      <div className="map-title">深圳市分区分时内涝风险热力</div>
      <MapContainer center={center} zoom={10} className="map" scrollWheelZoom={false}>
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution="&copy; OpenStreetMap &copy; CARTO"
        />
        {view.map((d) => {
          const lvl = d.at.level
          const r = 9 + d.at.prob * 24
          return (
            <CircleMarker
              key={d.id}
              center={d.center}
              radius={r}
              pathOptions={{
                color: levelColor(lvl),
                fillColor: levelColor(lvl),
                fillOpacity: 0.45,
                weight: 2,
              }}
            >
              <Tooltip direction="top">{d.name}</Tooltip>
              <Popup>
                <div className="pop">
                  <div className="pop-h">{d.name}</div>
                  <div className="pop-tag">{d.tag}</div>
                  <div className="pop-row">
                    <b style={{ color: levelColor(lvl) }}>
                      {LEVEL_LABELS[lvl]}风险
                    </b>
                    <span>概率 {(d.at.prob * 100).toFixed(0)}%</span>
                  </div>
                  <div className="pop-row">
                    <span>排水设计</span>
                    <span>{d.drainage} mm/h</span>
                  </div>
                  <div className="pop-row">
                    <span>本底脆弱性</span>
                    <span>{(d.vulnerability * 100).toFixed(0)}%</span>
                  </div>
                  <div className="pop-row">
                    <span>降雨超额</span>
                    <span>{d.at.excess} mm/h</span>
                  </div>
                  <div className="pop-row">
                    <span>主因</span>
                    <span>{d.at.driver}</span>
                  </div>
                  <div className="pop-row">
                    <span>峰值时刻</span>
                    <span>{fmtTime(d.peak.time)}（{d.peak.level_label}）</span>
                  </div>
                </div>
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>
      <div className="legend">
        {LEVEL_LABELS.map((l, i) => (
          <span key={l} className="lg">
            <i style={{ background: levelColor(i) }} />
            {l}
          </span>
        ))}
      </div>
    </div>
  )
}
