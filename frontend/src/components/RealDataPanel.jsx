import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, Popup } from 'react-leaflet'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, CartesianGrid,
  LineChart, Line, Legend,
} from 'recharts'
import { fetchJSON } from '../api'

const CENTER = [22.5431, 114.0579]

function levelColor(l) { return l > 1.0 ? '#d6452a' : l > 0.5 ? '#e08a1e' : l > 0.1 ? '#c9b458' : '#1f7a4d' }

export default function RealDataPanel() {
  const [data, setData] = useState(null)
  const [astDistrict, setAstDistrict] = useState('baoan')
  const [astObs, setAstObs] = useState(2.0)
  const [assim, setAssim] = useState(null)

  useEffect(() => { fetchJSON('/api/geo/realtime').then(setData).catch(() => setData(null)) }, [])

  async function runAssim() {
    setAssim(null)
    const r = await fetchJSON(`/api/assimilate/realtime?district=${astDistrict}&observed_h=${astObs}&at_hour=8`).catch(() => null)
    setAssim(r)
  }

  if (!data) return null
  const fps = data.floodpoints?.items || []
  const wlStations = (data.waterlevel?.top_stations || []).filter((s) => s.lat != null)
  const rain = data.rainfall?.items || []
  const as = assim?.assimilation

  return (
    <section className="card stage">
      <div className="card-h">
        真实数据 · 态势 + 数据同化
        <span className="hint">206 个真实易涝点 · 实时水位站 · CHIRPS 降雨 · 观测→同化→修正</span>
      </div>

      {/* 证据卡 */}
      <div className="verify-cards">
        <div className="ov-card" style={{ borderColor: '#145BFF' }}><div className="ov-k">真实易涝点</div><div className="ov-v">{data.floodpoints.count}</div></div>
        <div className="ov-card" style={{ borderColor: '#1f7a4d' }}><div className="ov-k">真实降雨样本</div><div className="ov-v">{data.rainfall.count} 天</div></div>
        <div className="ov-card" style={{ borderColor: '#e08a1e' }}><div className="ov-k">水位站(含坐标)</div><div className="ov-v">{wlStations.length}</div></div>
        <div className="ov-card" style={{ borderColor: '#d6452a' }}><div className="ov-k">积涝预警站</div><div className="ov-v" style={{ color: data.waterlevel?.flooding_count ? '#d6452a' : '#1f7a4d' }}>{data.waterlevel?.flooding_count || 0}</div></div>
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
        <div className="wm-h">数据同化闭环 · 真实观测 → 修正物理代理状态</div>
        <div className="wm-form">
          <label>行政区</label>
          <select value={astDistrict} onChange={(e) => setAstDistrict(e.target.value)}>
            {['futian','luohu','nanshan','baoan','longgang','yantian','longhua','pingshan','guangming','dapeng'].map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <label>观测水深(m)</label><input type="number" value={astObs} step="0.1" onChange={(e) => setAstObs(+e.target.value)} />
          <button className="mini" onClick={runAssim}>注入观测→同化</button>
        </div>
        {as && (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={as.corrected_risk.map((v, i) => ({ i, raw: as.raw_risk[i] * 100, corr: v * 100 }))} margin={{ top: 6, right: 10, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="rgba(255,255,255,.06)" />
              <XAxis dataKey="i" tick={{ fill: '#8C9098', fontSize: 10 }} interval={4} />
              <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={[0, 100]} unit="%" />
              <RTooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line dataKey="raw" name="同化前" stroke="#8C9098" dot={false} strokeWidth={1.2} />
              <Line dataKey="corr" name="同化后(观测钉住)" stroke="#145BFF" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
        {as && <div className="mc-note">残差 {as.residual} · 增益 K={as.gain} · {as.provenance}</div>}
        <div className="mc-note">{data.provenance?.note || '真实数据均来自深圳开放平台/CHIRPS/天地图（observed）'}</div>
      </div>
    </section>
  )
}
