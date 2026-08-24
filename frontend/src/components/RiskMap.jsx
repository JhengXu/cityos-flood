import { Fragment, useEffect, useMemo, useState } from 'react'
import {
  CircleMarker,
  ImageOverlay,
  MapContainer,
  Popup,
  TileLayer,
  Tooltip,
  ZoomControl,
} from 'react-leaflet'
import {
  depthQuantilesM,
  exceedanceProbability,
  fmtTime,
  formatDepthM,
  formatPercent,
  getGridImageBBox,
  getGridRisk,
} from '../api'

const clamp01 = (value = 0) => Math.max(0, Math.min(1, Number(value) || 0))
const depthLevel = (depthM = 0) => depthM >= 0.5 ? 4 : depthM >= 0.3 ? 3 : depthM >= 0.15 ? 2 : depthM >= 0.05 ? 1 : 0

const PALETTES = {
  depth: ['#38BDF8', '#2DD4BF', '#A3E635', '#FB923C', '#F43F5E'],
  probability: ['#BAE6FD', '#67E8F9', '#22D3EE', '#FBBF24', '#FB7185'],
  vulnerability: ['#60A5FA', '#22D3EE', '#2DD4BF', '#FBBF24', '#F97316'],
}

const MODE_META = {
  depth: {
    label: 'P50 水深',
    eyebrow: 'ENSEMBLE MEDIAN',
    legend: ['< 5cm', '5–15cm', '15–30cm', '30–50cm', '≥ 50cm'],
  },
  probability: {
    label: '超 15cm 概率',
    eyebrow: 'THRESHOLD PROBABILITY',
    legend: ['< 20%', '20–40%', '40–60%', '60–80%', '≥ 80%'],
  },
  vulnerability: {
    label: '本底脆弱性',
    eyebrow: 'BASE VULNERABILITY',
    legend: ['很低', '较低', '中等', '较高', '很高'],
  },
}

const bucketColor = (value, palette) => palette[Math.min(4, Math.floor(clamp01(value) * 5))]
const depthColor = (depthM) => PALETTES.depth[depthLevel(depthM)]
const districtShortName = (name = '') => name.replace(/(新区|区)$/, '')

function gridCellAt(grid, cell, cellIndex, hour) {
  const stepCount = Number(grid?.timeseries_encoding?.shape?.[1])
    || grid?.times?.length
    || cell.risk?.length
    || cell.depth_p50_m?.length
    || 0
  if (!stepCount) return { probability: 0, depthM: 0 }

  const timeIndex = Math.max(0, Math.min(hour, stepCount - 1))
  const offset = cellIndex * stepCount + timeIndex
  const probabilityBytes = grid?._riskU8
  const depthBytes = grid?._depthU16LEBytes
  const compactShape = grid?.timeseries_encoding?.shape
  const compactLengthValid = (
    compactShape?.[0] === grid?.cells?.length
    && probabilityBytes?.length === grid.cells.length * stepCount
    && depthBytes?.length === grid.cells.length * stepCount * 2
  )

  if (compactLengthValid) {
    const depthOffset = offset * 2
    return {
      probability: probabilityBytes[offset] / 255,
      depthM: (depthBytes[depthOffset] + 256 * depthBytes[depthOffset + 1]) / 1000,
    }
  }

  return {
    probability: clamp01(cell.risk?.[timeIndex]),
    depthM: Math.max(0, Number(cell.depth_p50_m?.[timeIndex]) || 0),
  }
}

function cellAppearance(mode, cell, probability, depthM) {
  if (mode === 'vulnerability') {
    const value = clamp01(cell.vulnerability)
    return {
      color: bucketColor(value, PALETTES.vulnerability),
      radius: 2.4 + value * 2.3,
      opacity: 0.32 + value * 0.48,
    }
  }

  if (mode === 'probability') {
    const active = probability >= 0.01
    return {
      color: bucketColor(probability, PALETTES.probability),
      radius: active ? 2.5 + probability * 2.7 : 1.25,
      opacity: active ? 0.24 + probability * 0.66 : 0.055,
    }
  }

  const active = depthM >= 0.005 || probability >= 0.01
  return {
    color: depthColor(depthM),
    radius: active ? 2.5 + Math.min(depthM / 0.5, 1) * 2.7 : 1.25,
    opacity: active ? 0.28 + Math.max(probability, Math.min(depthM / 0.5, 1)) * 0.62 : 0.055,
  }
}

export default function RiskMap({ data, view, hour }) {
  const center = data.city.center
  const [gridState, setGridState] = useState({ status: 'loading', data: null, error: '' })
  const [mode, setMode] = useState('depth')
  const [img, setImg] = useState(false)
  const [imgState, setImgState] = useState({ status: 'idle', meta: null, error: '' })

  useEffect(() => {
    let active = true
    setGridState({ status: 'loading', data: null, error: '' })
    getGridRisk(data.forecast_days, 0.018, data.forecast_run_id)
      .then((nextGrid) => {
        if (!active || nextGrid.forecast_run_id !== data.forecast_run_id) return
        setGridState({ status: 'ready', data: nextGrid, error: '' })
      })
      .catch((error) => {
        if (active) setGridState({ status: 'error', data: null, error: error?.message || '格点数据加载失败' })
      })
    return () => { active = false }
  }, [data.forecast_days, data.forecast_run_id])

  useEffect(() => {
    if (!img || mode !== 'depth') {
      setImgState({ status: 'idle', meta: null, error: '' })
      return undefined
    }

    let active = true
    const controller = new AbortController()
    setImgState({ status: 'loading', meta: null, error: '' })
    getGridImageBBox(data.forecast_days, data.forecast_run_id, hour, controller.signal)
      .then((meta) => {
        if (!active) return
        setImgState({ status: meta.empty ? 'empty' : 'image-loading', meta, error: '' })
      })
      .catch((error) => {
        if (active && error?.name !== 'AbortError') {
          setImgState({ status: 'error', meta: null, error: error?.message || '500m 图层加载失败' })
        }
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [data.forecast_days, data.forecast_run_id, hour, img, mode])

  const grid = gridState.data
  const cells = grid?.cells || []
  const imgMeta = imgState.meta
  const imgBounds = imgMeta
    ? [[imgMeta.south, imgMeta.west], [imgMeta.north, imgMeta.east]]
    : [[22.44, 113.72], [22.88, 114.66]]
  const imgURL = imgMeta?.url || `/api/risk/grid/image?res=0.0045&forecast_days=${data.forecast_days}&hour_index=${hour}&forecast_run_id=${encodeURIComponent(data.forecast_run_id || '')}`

  const cellView = useMemo(() => cells.map((cell, index) => {
    const values = gridCellAt(grid, cell, index, hour)
    return { cell, ...values, appearance: cellAppearance(mode, cell, values.probability, values.depthM) }
  }), [cells, grid, hour, mode])

  const citySummary = useMemo(() => view.reduce((summary, district) => {
    const depth = depthQuantilesM(district.at)
    const probability = exceedanceProbability(district.at, 0.15)
    return {
      maxDepth: Math.max(summary.maxDepth, depth.p50 || 0),
      maxProbability: Math.max(summary.maxProbability, probability || 0),
    }
  }, { maxDepth: 0, maxProbability: 0 }), [view])

  const metric = MODE_META[mode]

  return (
    <section className="map-wrap map-wrap-v2" aria-label="深圳内涝彩色态势地图">
      <header className="map-head-v2">
        <div className="map-heading">
          <div className="map-kicker">FORECAST MAP · {metric.eyebrow}</div>
          <h2 className="map-title-v2">深圳内涝 · 彩色态势图</h2>
          <div className="map-summary-row">
            <span className="map-status-dot live" />{fmtTime(data.hours?.[hour]) || '当前时次'}
            <span>最高 P50 <b>{formatDepthM(citySummary.maxDepth)}</b></span>
            <span>最高超阈概率 <b>{formatPercent(citySummary.maxProbability)}</b></span>
          </div>
        </div>
        <div className="map-toolbar" role="group" aria-label="地图指标切换">
          {Object.entries(MODE_META).map(([key, meta]) => (
            <button
              key={key}
              type="button"
              className={`map-chip ${mode === key ? 'on' : ''}`}
              aria-pressed={mode === key}
              onClick={() => {
                setMode(key)
                if (key !== 'depth') setImg(false)
              }}
            >
              {meta.label}
            </button>
          ))}
          <button
            type="button"
            className={`map-chip detail ${img ? 'on' : ''}`}
            aria-pressed={img}
            aria-busy={img && ['loading', 'image-loading'].includes(imgState.status)}
            disabled={mode !== 'depth'}
            title={mode === 'depth' ? '叠加当前时次约 500m GIS 下尺度图层' : '仅在 P50 水深模式可用'}
            onClick={() => setImg((value) => !value)}
          >
            500m 精细层
          </button>
        </div>
      </header>

      <div className="map-stage">
        <MapContainer
          center={center}
          zoom={10}
          minZoom={9}
          maxZoom={13}
          maxBounds={[[22.30, 113.45], [23.05, 114.95]]}
          maxBoundsViscosity={0.65}
          className="map map-colorful"
          scrollWheelZoom={false}
          zoomControl={false}
          preferCanvas
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            attribution="&copy; OpenStreetMap contributors &copy; CARTO"
          />
          <ZoomControl position="topright" />

          {img && mode === 'depth' && ['image-loading', 'ready'].includes(imgState.status) && (
            <ImageOverlay
              key={imgURL}
              url={imgURL}
              bounds={imgBounds}
              opacity={0.92}
              zIndex={320}
              eventHandlers={{
                load: () => setImgState((current) => current.meta?.url === imgURL
                  ? { ...current, status: 'ready', error: '' }
                  : current),
                error: () => setImgState((current) => current.meta?.url === imgURL
                  ? { ...current, status: 'error', error: '精细层图像解码或传输失败' }
                  : current),
              }}
            />
          )}

          {!(img && mode === 'depth' && ['image-loading', 'ready'].includes(imgState.status)) && cellView.map(({ cell, probability, depthM, appearance }, index) => (
            <CircleMarker
              key={`grid-${index}`}
              center={[cell.lat, cell.lon]}
              radius={appearance.radius}
              pathOptions={{
                color: appearance.color,
                fillColor: appearance.color,
                fillOpacity: appearance.opacity,
                opacity: Math.min(appearance.opacity + 0.12, 0.82),
                weight: 0.35,
              }}
            >
              <Tooltip direction="top" className="grid-tooltip" opacity={1}>
                <div className="grid-tip-head">{cell.district_id || '深圳格点'}</div>
                <div><span>P50 水深</span><b>{formatDepthM(depthM)}</b></div>
                <div><span>P(水深 ≥ 15cm)</span><b>{formatPercent(probability)}</b></div>
                <div><span>本底脆弱性</span><b>{formatPercent(cell.vulnerability)}</b></div>
                <div><span>地形</span><b>{Number(cell.elevation || 0).toFixed(0)}m · 不透水 {formatPercent(cell.impervious)}</b></div>
              </Tooltip>
            </CircleMarker>
          ))}

          {view.map((district) => {
            const depth = depthQuantilesM(district.at)
            const exceedance = exceedanceProbability(district.at, 0.15)
            const markerColor = depth.available ? depthColor(depth.p50) : bucketColor(exceedance, PALETTES.probability)
            return (
              <Fragment key={district.id}>
                <CircleMarker
                  center={district.center}
                  radius={14}
                  interactive={false}
                  pathOptions={{
                    color: markerColor,
                    fillColor: markerColor,
                    fillOpacity: 0.15,
                    opacity: 0.28,
                    weight: 1,
                  }}
                />
                <CircleMarker
                  center={district.center}
                  radius={6.5}
                  pathOptions={{
                    color: '#FFFFFF',
                    fillColor: markerColor,
                    fillOpacity: 0.98,
                    opacity: 0.96,
                    weight: 2,
                  }}
                >
                  <Tooltip permanent direction="top" offset={[0, -7]} className="district-label">
                    {districtShortName(district.name)}
                  </Tooltip>
                  <Popup>
                    <div className="pop">
                      <div className="pop-h">{district.name}</div>
                      <div className="pop-row"><b style={{ color: markerColor }}>{district.at.level_label || '—'}风险</b><strong>{depth.available ? formatDepthM(depth.p50) : formatPercent(exceedance)}</strong></div>
                      {depth.available && <div className="pop-row"><span>水深 P10–P90</span><span>{formatDepthM(depth.p10)}–{formatDepthM(depth.p90)}</span></div>}
                      <div className="pop-row"><span>P(水深 ≥ 15cm)</span><span>{formatPercent(exceedance)}</span></div>
                      <div className="pop-row"><span>排水设计</span><span>{district.drainage} mm/h</span></div>
                      <div className="pop-row"><span>本底脆弱性</span><span>{formatPercent(district.vulnerability)}</span></div>
                      <div className="pop-row"><span>主要驱动</span><span>{district.at.driver || '—'}</span></div>
                      <div className="pop-row"><span>预报峰值</span><span>{fmtTime(district.peak.time)}（{district.peak.level_label}）</span></div>
                    </div>
                  </Popup>
                </CircleMarker>
              </Fragment>
            )
          })}
        </MapContainer>

        {gridState.status === 'loading' && (
          <div className="map-grid-state" role="status">
            <span className="map-loader" />正在装载集合格点…
          </div>
        )}
        {gridState.status === 'error' && (
          <div className="map-grid-state error-state" role="alert">
            格点图层暂不可用 · {gridState.error}
          </div>
        )}

        {img && ['loading', 'image-loading'].includes(imgState.status) && (
          <div className="map-detail-state loading-state" role="status">
            <span className="map-loader" />正在生成当前时次 500m 精细层…
          </div>
        )}
        {img && imgState.status === 'empty' && (
          <div className="map-detail-state empty-state" role="status">
            <b>500m 图层正常</b>
            <span>当前时次没有可着色的 P50 积水；可拖动时间轴检查后续时次，持续为空即为本次预报的干态结果。</span>
          </div>
        )}
        {img && imgState.status === 'error' && (
          <div className="map-detail-state error-state" role="alert">
            <b>500m 图层不可用</b>
            <span>{imgState.error}</span>
          </div>
        )}
        {img && imgState.status === 'ready' && (
          <div className="map-detail-state ready-state" role="status">
            <b>500m 精细层已叠加</b>
            <span>{imgMeta?.visibleCells ?? '—'} 个着色像元 · 最大 P50 {formatDepthM(imgMeta?.maxDepthM)}</span>
          </div>
        )}

        <div className="map-legend-panel" aria-label={`${metric.label}图例`}>
          <div className="map-legend-title"><span>{metric.label}</span><small>{metric.eyebrow}</small></div>
          <div className="map-legend-bar" style={{ background: `linear-gradient(90deg, ${PALETTES[mode].join(', ')})` }} />
          <div className="map-legend-labels">
            {metric.legend.map((label) => <span key={label}>{label}</span>)}
          </div>
        </div>
      </div>

      <footer className="map-footnote">
        <span>{img && imgMeta
          ? `${Number(imgMeta.totalCells || 0).toLocaleString()} 格 · 约 0.5km 精细栅格`
          : grid
            ? `${grid.n_cells || cells.length} 格 · 约 ${((grid.resolution_deg || 0.018) * 111).toFixed(1)}km`
            : '集合格点载入中'}</span>
        <span className="map-boundary-note">区名为中心参考点；格点是有界 GIS 下尺度，非完整行政边界裁切或二维水动力淹没范围。</span>
      </footer>
    </section>
  )
}
