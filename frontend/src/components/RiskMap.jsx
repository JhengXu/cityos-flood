import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, ImageOverlay } from 'react-leaflet'
import { fmtTime, levelColor, LEVEL_LABELS, getGridRisk, getGridImageBBox } from '../api'

export default function RiskMap({ data, view, hour }) {
  const center = data.city.center
  const [grid, setGrid] = useState(null)
  const [mode, setMode] = useState('risk')   // risk | vuln
  const [img, setImg] = useState(false)      // 500m 精网格热力开关
  const [imgBounds, setImgBounds] = useState(null)

  useEffect(() => {
    getGridRisk(2, 0.018).then((d) => setGrid(d)).catch(() => setGrid(null))
  }, [])

  // 500m 网格 bbox（深圳 22.44-22.88, 113.72-114.66）——与后端一致，避免依赖 HEAD 头
  const SZ_BBOX = { south: 22.44, west: 113.72, north: 22.88, east: 114.66 }
  useEffect(() => { if (img) setImgBounds(SZ_BBOX); else setImgBounds(null) }, [img])

  const cells = grid?.cells || []
  const imgURL = '/api/risk/grid/image?res=0.0045&_=' + (img ? '1' : '0')
  return (
    <div className="map-wrap">
      <div className="map-title">
        深圳市分区分时内涝风险热力
        <span className="map-mode">
          <button className={`mini ${mode === 'risk' ? 'on' : ''}`} onClick={() => setMode('risk')}>净风险</button>
          <button className={`mini ${mode === 'vuln' ? 'on' : ''}`} onClick={() => setMode('vuln')}>本底脆弱性</button>
          <button className={`mini ${img ? 'on' : ''}`} onClick={() => setImg((v) => !v)}>500m 精网格</button>
          <span className="hint8">{grid ? `${grid.n_cells} 格 · ${(grid.resolution_deg * 111).toFixed(1)}km` : ''}</span>
        </span>
      </div>
      <MapContainer center={center} zoom={10} className="map" scrollWheelZoom={false}>
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution="&copy; OpenStreetMap &copy; CARTO"
        />
        {/* 500m 精网格热力（PNG 层） */}
        {img && imgBounds && (
          <ImageOverlay url={imgURL} bounds={[[imgBounds.south, imgBounds.west], [imgBounds.north, imgBounds.east]]} opacity={0.9} />
        )}
        {/* 细粒度网格热力 */}
        {cells.map((c, i) => {
          const val = mode === 'risk' ? (c.risk[Math.min(hour, c.risk.length - 1)] || 0) : c.vulnerability
          const lvl = Math.min(4, Math.floor(val * 5))
          return (
            <CircleMarker key={'g' + i} center={[c.lat, c.lon]} radius={2.2}
              pathOptions={{ color: levelColor(lvl), fillColor: levelColor(lvl), fillOpacity: 0.55 + val * 0.45, weight: 0.2 }}>
              <Tooltip direction="top">
                {mode === 'risk' ? `风险 ${val.toFixed(2)}` : `脆弱性 ${val.toFixed(2)}`} · {c.district_id} 高程{c.elevation}m 不透水{c.impervious}
              </Tooltip>
            </CircleMarker>
          )
        })}
        {/* 区县中心参考 */}
        {view.map((d) => (
          <CircleMarker key={d.id} center={d.center} radius={7}
            pathOptions={{ color: levelColor(d.at.level), fillColor: 'transparent', weight: 2, dashArray: '3 3' }}>
            <Tooltip direction="top">{d.name}</Tooltip>
            <Popup>
              <div className="pop">
                <div className="pop-h">{d.name}</div>
                <div className="pop-row"><b style={{ color: levelColor(d.at.level) }}>{d.at.level_label}风险</b><span>{(d.at.prob * 100).toFixed(0)}%</span></div>
                <div className="pop-row"><span>排水设计</span><span>{d.drainage} mm/h</span></div>
                <div className="pop-row"><span>本底脆弱性</span><span>{(d.vulnerability * 100).toFixed(0)}%</span></div>
                <div className="pop-row"><span>主因</span><span>{d.at.driver}</span></div>
                <div className="pop-row"><span>峰值</span><span>{fmtTime(d.peak.time)}（{d.peak.level_label}）</span></div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      <div className="legend">
        {LEVEL_LABELS.map((l, i) => (
          <span key={l} className="lg"><i style={{ background: levelColor(i) }} />{l}</span>
        ))}
        <span className="lg"><i style={{ background: 'transparent', border: '1px dashed #8C9098' }} />区界</span>
      </div>
    </div>
  )
}
