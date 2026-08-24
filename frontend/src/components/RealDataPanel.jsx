import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, Popup } from 'react-leaflet'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, CartesianGrid,
  LineChart, Line, Legend,
} from 'recharts'
import { fetchJSON, formatDepthM, getRealtimeAssimilate } from '../api'

const CENTER = [22.5431, 114.0579]

function levelColor(l) { return l > 1.0 ? '#d6452a' : l > 0.5 ? '#e08a1e' : l > 0.1 ? '#c9b458' : '#1f7a4d' }

export default function RealDataPanel({ predictData }) {
  const [data, setData] = useState(null)
  const [astDistrict, setAstDistrict] = useState('baoan')
  const [astObs, setAstObs] = useState(0.30)
  const [astHour, setAstHour] = useState(8)
  const [assim, setAssim] = useState(null)
  const forecastDays = Number(predictData?.forecast_days) || 3
  const forecastRunId = predictData?.forecast_run_id || null
  const runKey = `${forecastDays}:${forecastRunId || ''}`
  const activeRunRef = useRef(runKey)
  const assimilationRequestRef = useRef(0)
  activeRunRef.current = runKey

  useEffect(() => { fetchJSON('/api/geo/realtime').then(setData).catch(() => setData(null)) }, [])
  useEffect(() => {
    assimilationRequestRef.current += 1
    setAssim(null)
  }, [runKey])

  async function runAssim() {
    setAssim(null)
    const expectedRunKey = runKey
    const expectedRunId = forecastRunId
    const requestId = ++assimilationRequestRef.current
    const r = await getRealtimeAssimilate({
      district: astDistrict,
      observed_h: astObs,
      at_hour: astHour,
      forecast_days: forecastDays,
      ...(forecastRunId ? { forecast_run_id: forecastRunId } : {}),
    })
      .catch((error) => ({ status: 'error', hint: error.message }))
    if (
      requestId === assimilationRequestRef.current
      && activeRunRef.current === expectedRunKey
      && (!expectedRunId || r?.forecast_run_id === expectedRunId || r?.status === 'error')
    ) setAssim(r)
  }

  if (!data) return null
  const fps = data.floodpoints?.items || []
  const wlStations = (data.waterlevel?.top_stations || []).filter((s) => s.lat != null)
  const rain = data.rainfall?.items || []
  const qc = data.waterlevel_quality || {}
  const gis = data.gis_assets || {}
  const readiness = data.data_readiness || data.forecast_training_readiness || data.observation_readiness || data.readiness || {}
  const assimilation = assim?.assimilation || assim
  const assimilationStatus = assim?.status || assimilation?.status
  const rawDepthM = assimilation?.raw_depth_p50_m || assimilation?.raw_h || assimilation?.prior_depth_trajectory_m
  const correctedDepthM = assimilation?.corrected_depth_p50_m || assimilation?.corrected_h || assimilation?.posterior_depth_trajectory_m
  const rawDepthMm = assimilation?.raw_depth_mm || assimilation?.prior_depth_trajectory_mm || assimilation?.forecast_depth_mm
  const correctedDepthMm = assimilation?.corrected_depth_mm || assimilation?.posterior_depth_trajectory_mm || assimilation?.analysis_depth_mm
  const scalarSeries = (before, after) => Array.isArray(before) && Array.isArray(after)
    && before.length === after.length && before.every((v) => Number.isFinite(Number(v)))
    && after.every((v) => Number.isFinite(Number(v)))
  const depthSeriesM = scalarSeries(rawDepthM, correctedDepthM)
  const depthSeriesMm = scalarSeries(rawDepthMm, correctedDepthMm)
  const depthSeries = depthSeriesM || depthSeriesMm
  const riskSeries = Array.isArray(assimilation?.raw_risk) && Array.isArray(assimilation?.corrected_risk)
    && assimilation.raw_risk.length === assimilation.corrected_risk.length
  const assimilationChart = depthSeriesM
    ? correctedDepthM.map((value, i) => ({ i, raw: rawDepthM[i], corr: value }))
    : depthSeriesMm
      ? correctedDepthMm.map((value, i) => ({ i, raw: rawDepthMm[i], corr: value }))
    : riskSeries
      ? assimilation.corrected_risk.map((value, i) => ({ i, raw: assimilation.raw_risk[i] * 100, corr: value * 100 }))
      : []

  return (
    <section className="card stage">
      <div className="card-h">
        观测数据 · 态势 + 数据同化
        <span className="hint">易涝点静态资产 · 质控水位缓存 · CHIRPS 逐日降雨 · 时效合格观测才会自动同化</span>
      </div>

      {/* 证据卡 */}
      <div className="verify-cards">
        <div className="ov-card" style={{ borderColor: '#145BFF' }}><div className="ov-k">真实易涝点</div><div className="ov-v">{data.floodpoints.count}</div></div>
        <div className="ov-card" style={{ borderColor: '#1f7a4d' }}><div className="ov-k">真实降雨样本</div><div className="ov-v">{data.rainfall.count} 天</div></div>
        <div className="ov-card" style={{ borderColor: '#e08a1e' }}><div className="ov-k">当前快照站(含坐标)</div><div className="ov-v">{wlStations.length}</div></div>
        <div className="ov-card" style={{ borderColor: '#d6452a' }}><div className="ov-k">快照中积涝提示</div><div className="ov-v" style={{ color: data.waterlevel?.flooding_count ? '#d6452a' : '#1f7a4d' }}>{data.waterlevel?.flooding_count || 0}</div></div>
        <div className="ov-card"><div className="ov-k">站点空间特征</div><div className="ov-v">{data.station_features?.count || 0}</div><div className="ov-sub">高程/不透水/距水体</div></div>
        <div className="ov-card"><div className="ov-k">小时水位质控</div><div className="ov-v">{qc.hourly_rows || 0}</div><div className="ov-sub">{qc.stations || 0}站 · 北京时间</div></div>
      </div>

      {Object.keys(readiness).length > 0 && (
        <div className={`status-banner ${readiness.forecast_training_ready ? 'ready' : 'limited'}`}>
          <b>{readiness.forecast_training_ready ? '已达到独立训练最低数据门槛' : '当前仅能支持接入验证/干状态先验'}</b>
          <span>
            {readiness.duration_hours != null ? `${readiness.duration_hours}小时 · ` : ''}
            {readiness.stations != null ? `${readiness.stations}站 · ` : ''}
            {readiness.independent_flood_events != null ? `${readiness.independent_flood_events}个独立洪涝事件。` : ''}
            {readiness.reason || ''}
          </span>
        </div>
      )}

      <div className="wm-cell" style={{ marginTop: 14 }}>
        <div className="wm-h">已接入 GIS 与水位质量报告</div>
        <div className="prov-grid">
          <div className="prov-line"><b>DEM / 不透水格网</b><span>{gis.dem_points || 0} / {gis.impervious_cells || 0}</span></div>
          <div className="prov-line"><b>路段 / 水系要素</b><span>{gis.road_segments || 0} / {gis.water_features || 0}</span></div>
          <div className="prov-line"><b>去除重复记录</b><span>{qc.duplicate_rows_removed || 0}</span></div>
          <div className="prov-line"><b>原始时间说明</b><span>{qc.timezone_assumption || '—'}</span></div>
        </div>
        <div className="mc-note">原始水位没有时区字段，现按深圳市政数据本地时间解释并显式保存为 Asia/Shanghai (+08:00)；这是可审计假设，不等同于数据提供方元数据确认。</div>
      </div>

      <div className="rd-grid">
        {/* 地图：真实易涝点 + 实时水位站 */}
        <div className="rd-map">
          <div className="realmap">
            <MapContainer center={CENTER} zoom={10} className="map" scrollWheelZoom={false}>
              <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution="© OpenStreetMap © CARTO" />
              {fps.slice(0, 300).map((p, i) => (
                <CircleMarker key={i} center={[p.lat, p.lon]} radius={3}
                  pathOptions={{ color: 'rgba(20,91,255,.55)', fillColor: '#145BFF', fillOpacity: .6, weight: 1 }}>
                  <Tooltip direction="top">{p.district}{p.street} · {p.location}</Tooltip>
                </CircleMarker>
              ))}
              {wlStations.map((s, i) => (
                <CircleMarker key={'s' + i} center={[s.lat, s.lon]} radius={3 + s.level * 4}
                  pathOptions={{ color: levelColor(s.level), fillColor: levelColor(s.level), fillOpacity: .8, weight: 2 }}>
                  <Popup>
                    <div className="pop-h">{s.name}</div>
                    <div>水位 {s.level}m {s.flooding ? '· 积涝!' : ''}</div>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>
          <div className="rd-legend"><i style={{ background: '#145BFF' }} />真实易涝点　<i style={{ background: '#d6452a' }} />水位站≥提示</div>
        </div>

        {/* 真实降雨 */}
        <div className="rd-cell">
          <div className="wm-h">真实降雨（CHIRPS 逐日·全市最大）</div>
          <ResponsiveContainer width="100%" height={170}>
            <BarChart data={rain.map((r) => ({ d: r.date.slice(5), mm: r.max_mm }))} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="rgba(255,255,255,.06)" />
              <XAxis dataKey="d" tick={{ fill: '#8C9098', fontSize: 9 }} interval={Math.floor(rain.length / 7)} />
              <YAxis tick={{ fill: '#8C9098', fontSize: 9 }} />
              <RTooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
              <Bar dataKey="mm" fill="#145BFF" name="最大降雨mm" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 数据同化闭环 */}
      <div className="wm-cell" style={{ marginTop: 14 }}>
        <div className="wm-h">数据同化闭环 · 水深观测 → 局地 EnSRF 修正存水状态</div>
        <div className="wm-form">
          <label>行政区</label>
          <select value={astDistrict} onChange={(e) => setAstDistrict(e.target.value)}>
            {['futian','luohu','nanshan','baoan','longgang','yantian','longhua','pingshan','guangming','dapeng'].map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <label>观测水深(m)</label><input type="number" min="0" value={astObs} step="0.01" onChange={(e) => setAstObs(+e.target.value)} />
          <label>观测有效时效(h)</label><input type="number" min="0" max={forecastDays * 24 - 1} value={astHour} onChange={(e) => setAstHour(+e.target.value)} />
          <button className="mini" onClick={runAssim}>注入观测→同化</button>
        </div>
        {assim && (assimilationStatus === 'unavailable' || assimilationStatus === 'insufficient_data' || assimilationStatus === 'error') && (
          <div className="status-banner limited">
            <b>同化未执行</b>
            <span>{assimilation?.hint || assimilation?.reason || assim?.hint || '当前没有时效合格的区级水深观测。'}</span>
          </div>
        )}
        {assimilationChart.length > 0 && (
          <>
            {(assimilation?.prior_mean_depth_m ?? assimilation?.prior_depth_m) != null && (
              <div className="assim-kpis">
                <div className="wm-kpi"><span>注入时刻集合均值</span><b>{formatDepthM(assimilation.prior_mean_depth_m ?? assimilation.prior_depth_m)} → {formatDepthM(assimilation.posterior_mean_depth_m ?? assimilation.posterior_depth_m)}</b></div>
                <div className="wm-kpi"><span>集合标准差</span><b>{formatDepthM(assimilation.prior_std_m)} → {formatDepthM(assimilation.posterior_std_m)}</b></div>
              </div>
            )}
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={assimilationChart} margin={{ top: 6, right: 10, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="rgba(255,255,255,.06)" />
                <XAxis dataKey="i" tick={{ fill: '#8C9098', fontSize: 10 }} interval={4} />
                <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={depthSeries ? ['auto', 'auto'] : [0, 100]} unit={depthSeriesM ? 'm' : (depthSeriesMm ? 'mm' : '%')} />
                <RTooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line dataKey="raw" name="同化前" stroke="#8C9098" dot={false} strokeWidth={1.2} />
                <Line dataKey="corr" name="同化后(EnSRF)" stroke="#145BFF" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </>
        )}
        {assimilationChart.length > 0 && <div className="mc-note">输入观测 {formatDepthM(astObs)} · 创新/残差 {assimilation.innovation_mm != null ? `${assimilation.innovation_mm}mm` : (assimilation.residual != null ? `${assimilation.residual}${assimilation.residual_unit || 'm'}` : '—')} · {assimilation.provenance || ''}</div>}
        <div className="mc-note">{data.provenance?.note || '各数据集的观测时间窗、空间分辨率和标签含义不同，不可直接等同为内涝事件监督标签。'}</div>
      </div>
    </section>
  )
}
