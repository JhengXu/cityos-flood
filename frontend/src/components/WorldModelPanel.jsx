import { useEffect, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts'
import { getSpatial, getAccessibility, getCounterfactual, getAssimilate, levelColor } from '../api'

const NAMES = { futian: '福田', luohu: '罗湖', nanshan: '南山', baoan: '宝安', longgang: '龙岗', yantian: '盐田', longhua: '龙华', pingshan: '坪山', guangming: '光明', dapeng: '大鹏' }

export default function WorldModelPanel({ predictData }) {
  const [spatial, setSpatial] = useState(null)
  const [acc, setAcc] = useState(null)
  const [cf, setCf] = useState(null)
  const [assim, setAssim] = useState(null)
  const [close, setClose] = useState('luohu,baoan')
  const [pump, setPump] = useState('futian:0.5')
  const [astDistrict, setAstDistrict] = useState('baoan')
  const [astObs, setAstObs] = useState(30)
  const [astHour, setAstHour] = useState(6)

  useEffect(() => { getSpatial().then(setSpatial).catch(() => setSpatial(null)) }, [])
  useEffect(() => { getAccessibility().then(setAcc).catch(() => setAcc(null)) }, [])

  async function runCf() {
    setCf(null)
    const r = await getCounterfactual({ close, pump }).catch(() => null)
    setCf(r)
  }
  async function runAssim() {
    setAssim(null)
    const r = await getAssimilate({ district: astDistrict, observed_h: astObs, at_hour: astHour }).catch(() => null)
    setAssim(r)
  }

  // hazard 状态演化：从预测数据里取各个区的 surrogate 概率轨迹
  const districts = predictData?.districts || []
  const hazData = districts[0] ? districts[0].series.map((s, i) => {
    const row = { h: s.time ? s.time.slice(5, 16) : `+${i}h` }
    districts.forEach((dd) => {
      const sur = dd.series[i]?.surrogate
      row[dd.id] = sur ? Math.round(sur.prob * 100) : null
    })
    return row
  }) : []

  return (
    <section className="card stage">
      <div className="card-h">
        世界行为模型 · WAM
        <span className="hint">物理代理状态 h(t) → 空间耦合 → 可达性/反事实干预 → 数据同化</span>
      </div>
      <div className="mc-note">
        模型：h_i(t+Δt)=max[0, h_i(t)+α_i·(R_i−C_i)₊+Σw_ji·h_j(t)−β_i·h_i(t)]　·　物理方程提供边界，数据校准 α/β（不是黑箱）
      </div>

      <div className="wm-grid">
        {/* ① 物理代理状态演化 */}
        <div className="wm-cell wm-hazard">
          <div className="wm-h">① 物理代理状态 h(t) 演化（分区分时）</div>
          {hazData.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={hazData} margin={{ top: 6, right: 12, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="rgba(255,255,255,.06)" />
                <XAxis dataKey="h" tick={{ fill: '#8C9098', fontSize: 9 }} interval={Math.floor(hazData.length / 8)} />
                <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={[0, 100]} unit="%" />
                <Tooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {districts.slice(0, 5).map((dd) => (
                  <Line key={dd.id} type="monotone" dataKey={dd.id} name={NAMES[dd.id]} stroke="rgba(20,91,255,.85)" strokeWidth={1.2} dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : <div className="empty">加载预测数据后展示</div>}
        </div>

        {/* ② 空间耦合表 */}
        <div className="wm-cell">
          <div className="wm-h">② 空间耦合表</div>
          {spatial ? (
            <>
              <div className="wm-row2"><span>区↔区 路网边</span><b>{spatial.district_edges ? Object.keys(spatial.district_edges).length : 0} 区</b></div>
              <div className="wm-row2"><span>设施→接入区</span><b>{spatial.facility_access ? Object.keys(spatial.facility_access).length : 0} 项</b></div>
              <div className="wm-row2"><span>格点→区映射</span><b>{spatial.grid_to_district_cells} 格点</b></div>
              <div className="wm-prov">
                {Object.entries(spatial.provenance || {}).map(([k, v]) => (
                  <div className="wm-prov-row" key={k}><span>{k}</span><i>{v}</i></div>
                ))}
              </div>
            </>
          ) : <div className="empty">加载中…</div>}
        </div>

        {/* ③ 可达性 + 道路损伤 */}
        <div className="wm-cell">
          <div className="wm-h">③ 道路损伤 · 动态可达性</div>
          {acc ? (
            <>
              <div className="wm-kpi"><span>城市可达人口占比</span><b>{(acc.city_reachable_pop_share * 100).toFixed(1)}%</b></div>
              <div className="wm-kpi dim"><span>相比无损伤基线</span><b>{(acc.city_delta * 100).toFixed(1)}%</b></div>
              <div className="wm-dmg">
                {Object.entries(acc.damage || {}).slice(0, 6).map(([k, v]) => (
                  <div className="wm-dmg-row" key={k}><span>{NAMES[k] || k}</span><i style={{ width: `${v * 100}%` }} /></div>
                ))}
              </div>
              <div className="wm-prov"><span className="prov-tag">provenance</span></div>
            </>
          ) : <div className="empty">加载中…</div>}
        </div>
      </div>

      {/* ④ 反事实干预 + ⑤ 数据同化 */}
      <div className="wm-grid">
        <div className="wm-cell">
          <div className="wm-h">④ 反事实干预（推演-评估-择优）</div>
          <div className="wm-form">
            <label>封路(逗号区)</label><input value={close} onChange={(e) => setClose(e.target.value)} />
            <label>抽排增效 区:系数</label><input value={pump} onChange={(e) => setPump(e.target.value)} />
            <button className="mini" onClick={runCf}>运行反事实</button>
          </div>
          {cf && (
            <div className="wm-cf">
              <div className="wm-kpi"><span>基线可达占比</span><b>{(cf.baseline.city_reachable_pop_share * 100).toFixed(1)}%</b></div>
              <div className="wm-kpi"><span>干预后可达占比</span><b>{(cf.intervention.city_reachable_pop_share * 100).toFixed(1)}%</b></div>
              <div className="wm-kpi big"><span>Δ 城市可达</span><b style={{ color: cf.delta_city_reachable_pop_share < 0 ? '#d6452a' : '#1f7a4d' }}>
                {(cf.delta_city_reachable_pop_share * 100).toFixed(1)}%</b></div>
            </div>
          )}
        </div>
        <div className="wm-cell">
          <div className="wm-h">⑤ 数据同化（观测注入）</div>
          <div className="wm-form">
            <label>行政区</label>
            <select value={astDistrict} onChange={(e) => setAstDistrict(e.target.value)}>
              {Object.entries(NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label>观测水深</label><input type="number" value={astObs} onChange={(e) => setAstObs(+e.target.value)} />
            <label>注入时刻(h)</label><input type="number" value={astHour} onChange={(e) => setAstHour(+e.target.value)} />
            <button className="mini" onClick={runAssim}>注入观测</button>
          </div>
          {assim && (
            <>
              <div className="wm-kpi"><span>残差</span><b>{assim.residual}</b></div>
              <ResponsiveContainer width="100%" height={120}>
                <LineChart data={assim.corrected_risk.map((v, i) => ({ i, raw: assim.raw_risk[i] * 100, corr: v * 100 }))} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid stroke="rgba(255,255,255,.06)" />
                  <XAxis dataKey="i" tick={{ fill: '#8C9098', fontSize: 9 }} interval={6} />
                  <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={[0, 100]} unit="%" />
                  <Tooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line dataKey="raw" name="同化前" stroke="#8C9098" dot={false} strokeWidth={1.2} />
                  <Line dataKey="corr" name="同化后" stroke="#145BFF" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
