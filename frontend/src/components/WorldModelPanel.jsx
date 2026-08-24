import { useEffect, useRef, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts'
import {
  getSpatial, getAccessibility, getCounterfactual, getAssimilate,
  depthQuantilesM, formatDepthM,
} from '../api'

const NAMES = { futian: '福田', luohu: '罗湖', nanshan: '南山', baoan: '宝安', longgang: '龙岗', yantian: '盐田', longhua: '龙华', pingshan: '坪山', guangming: '光明', dapeng: '大鹏' }

export default function WorldModelPanel({ predictData }) {
  const [spatial, setSpatial] = useState(null)
  const [acc, setAcc] = useState(null)
  const [cf, setCf] = useState(null)
  const [assim, setAssim] = useState(null)
  const [close, setClose] = useState('luohu,baoan')
  const [pump, setPump] = useState('futian:0.5')
  const [astDistrict, setAstDistrict] = useState('baoan')
  const [astObs, setAstObs] = useState(0.30)
  const [astHour, setAstHour] = useState(6)
  const forecastDays = Number(predictData?.forecast_days) || 3
  const forecastRunId = predictData?.forecast_run_id || null
  const runKey = `${forecastDays}:${forecastRunId || ''}`
  const activeRunRef = useRef(runKey)
  const cfRequestRef = useRef(0)
  const assimilationRequestRef = useRef(0)
  activeRunRef.current = runKey

  const runParams = () => ({
    forecast_days: forecastDays,
    ...(forecastRunId ? { forecast_run_id: forecastRunId } : {}),
  })

  useEffect(() => { getSpatial().then(setSpatial).catch(() => setSpatial(null)) }, [])
  useEffect(() => {
    let active = true
    cfRequestRef.current += 1
    assimilationRequestRef.current += 1
    setAcc(null)
    setCf(null)
    setAssim(null)
    getAccessibility(runParams())
      .then((result) => {
        if (active && (!forecastRunId || result.forecast_run_id === forecastRunId)) setAcc(result)
      })
      .catch(() => { if (active) setAcc(null) })
    return () => { active = false }
  }, [forecastDays, forecastRunId])

  async function runCf() {
    setCf(null)
    const expectedRunKey = runKey
    const expectedRunId = forecastRunId
    const requestId = ++cfRequestRef.current
    const r = await getCounterfactual({ ...runParams(), close, pump }).catch(() => null)
    if (
      requestId === cfRequestRef.current
      && activeRunRef.current === expectedRunKey
      && (!expectedRunId || r?.forecast_run_id === expectedRunId)
    ) setCf(r)
  }
  async function runAssim() {
    setAssim(null)
    const expectedRunKey = runKey
    const expectedRunId = forecastRunId
    const requestId = ++assimilationRequestRef.current
    const r = await getAssimilate({
      ...runParams(), district: astDistrict, observed_h: astObs, at_hour: astHour,
    })
      .catch((error) => ({ status: 'error', hint: error.message }))
    if (
      requestId === assimilationRequestRef.current
      && activeRunRef.current === expectedRunKey
      && (!expectedRunId || r?.forecast_run_id === expectedRunId || r?.status === 'error')
    ) setAssim(r)
  }

  // 新模型以集合水深为主轨迹；旧后端未升级时才回退到概率。
  const districts = predictData?.districts || []
  const hazData = districts[0] ? districts[0].series.map((s, i) => {
    const row = { h: s.time ? s.time.slice(5, 16) : `+${i}h` }
    districts.forEach((dd) => {
      const point = dd.series[i] || {}
      const depth = depthQuantilesM(point)
      row[dd.id] = depth.available ? +(depth.p50 * 100).toFixed(1) : (point.prob != null ? +(point.prob * 100).toFixed(1) : null)
    })
    return row
  }) : []
  const depthMode = districts.some((district) => district.series?.some((point) => depthQuantilesM(point).available))
  const assimData = assim?.assimilation || assim
  const assimStatus = assim?.status || assimData?.status
  const rawDepthM = assimData?.raw_depth_p50_m || assimData?.raw_h || assimData?.prior_depth_trajectory_m
  const correctedDepthM = assimData?.corrected_depth_p50_m || assimData?.corrected_h || assimData?.posterior_depth_trajectory_m
  const rawDepthMm = assimData?.raw_depth_mm || assimData?.prior_depth_trajectory_mm || assimData?.forecast_depth_mm
  const correctedDepthMm = assimData?.corrected_depth_mm || assimData?.posterior_depth_trajectory_mm || assimData?.analysis_depth_mm
  const scalarSeries = (before, after) => Array.isArray(before) && Array.isArray(after)
    && before.length === after.length && before.every((v) => Number.isFinite(Number(v)))
    && after.every((v) => Number.isFinite(Number(v)))
  const hasDepthTrajectoryM = scalarSeries(rawDepthM, correctedDepthM)
  const hasDepthTrajectoryMm = scalarSeries(rawDepthMm, correctedDepthMm)
  const hasDepthTrajectory = hasDepthTrajectoryM || hasDepthTrajectoryMm
  const rawRisk = assimData?.raw_risk
  const correctedRisk = assimData?.corrected_risk
  const hasRiskTrajectory = Array.isArray(rawRisk) && Array.isArray(correctedRisk) && rawRisk.length === correctedRisk.length
  const assimChart = hasDepthTrajectoryM
    ? correctedDepthM.map((value, i) => ({ i, raw: rawDepthM[i], corr: value }))
    : hasDepthTrajectoryMm
      ? correctedDepthMm.map((value, i) => ({ i, raw: rawDepthMm[i], corr: value }))
    : hasRiskTrajectory
      ? correctedRisk.map((value, i) => ({ i, raw: rawRisk[i] * 100, corr: value * 100 }))
      : []
  const palette = ['#145BFF', '#45a3ff', '#1f7a4d', '#e08a1e', '#d6452a']

  return (
    <section className="card stage">
      <div className="card-h">
        守恒状态空间世界模型 · Ensemble + 局地 EnSRF
        <span className="hint">降雨/潮位驱动 → 存水守恒与下泄路由 → 集合不确定性 → 观测同化</span>
      </div>
      <div className="mc-note">
        Sᵢ(t+Δt)=Sᵢ(t)+径流−排水−路由流出+路由流入−边界外排；水深由连续两段式蓄水曲线反演。图通量同步更新且逐步审计质量守恒；分位数反映参数不确定性，不等同于已经独立灾情数据校准。
      </div>

      <div className="wm-grid">
        {/* ① 存水状态演化 */}
        <div className="wm-cell wm-hazard">
          <div className="wm-h">① {depthMode ? '集合中位积水深度' : '兼容概率轨迹'}（分区分时）</div>
          {hazData.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={hazData} margin={{ top: 6, right: 12, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="rgba(255,255,255,.06)" />
                <XAxis dataKey="h" tick={{ fill: '#8C9098', fontSize: 9 }} interval={Math.floor(hazData.length / 8)} />
                <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={depthMode ? ['auto', 'auto'] : [0, 100]} unit={depthMode ? 'cm' : '%'} />
                <Tooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {districts.slice(0, 5).map((dd) => (
                  <Line key={dd.id} type="monotone" dataKey={dd.id} name={NAMES[dd.id]} stroke={palette[districts.indexOf(dd) % palette.length]} strokeWidth={1.5} dot={false} />
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
              <div className="wm-row2"><span>区↔区 假设耦合边</span><b>{spatial.district_edges ? Object.values(spatial.district_edges).reduce((sum, count) => sum + count, 0) : 0} 条</b></div>
              <div className="wm-row2"><span>水动力有向边</span><b>{spatial.hydraulic_edges?.length || 0} 条</b></div>
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
            <label>观测水深(m)</label><input type="number" min="0" step="0.01" value={astObs} onChange={(e) => setAstObs(+e.target.value)} />
            <label>注入时刻(h)</label><input type="number" value={astHour} onChange={(e) => setAstHour(+e.target.value)} />
            <button className="mini" onClick={runAssim}>注入观测</button>
          </div>
          {assim && (assimStatus === 'unavailable' || assimStatus === 'insufficient_data' || assimStatus === 'error') && (
            <div className="status-banner limited">
              <b>本次无法同化</b>
              <span>{assimData?.hint || assimData?.reason || assim?.hint || '没有符合时效与质控要求的水深观测。'}</span>
            </div>
          )}
          {assimChart.length > 0 && (
            <>
              <div className="wm-kpi"><span>观测创新/残差</span><b>{assimData?.innovation_mm != null ? `${assimData.innovation_mm}mm` : (assimData?.residual != null ? `${assimData.residual}${assimData.residual_unit || 'm'}` : '—')}</b></div>
              {(assimData?.prior_mean_depth_m ?? assimData?.prior_depth_m) != null && <div className="wm-kpi"><span>注入时刻集合均值</span><b>{formatDepthM(assimData.prior_mean_depth_m ?? assimData.prior_depth_m)} → {formatDepthM(assimData.posterior_mean_depth_m ?? assimData.posterior_depth_m)}</b></div>}
              {assimData?.prior_std_m != null && <div className="wm-kpi dim"><span>集合标准差</span><b>{formatDepthM(assimData.prior_std_m)} → {formatDepthM(assimData.posterior_std_m)}</b></div>}
              <ResponsiveContainer width="100%" height={120}>
                <LineChart data={assimChart} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid stroke="rgba(255,255,255,.06)" />
                  <XAxis dataKey="i" tick={{ fill: '#8C9098', fontSize: 9 }} interval={6} />
                  <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={hasDepthTrajectory ? ['auto', 'auto'] : [0, 100]} unit={hasDepthTrajectoryM ? 'm' : (hasDepthTrajectoryMm ? 'mm' : '%')} />
                  <Tooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line dataKey="raw" name="同化前" stroke="#8C9098" dot={false} strokeWidth={1.2} />
                  <Line dataKey="corr" name="同化后" stroke="#145BFF" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
              <div className="mc-note">
                {hasDepthTrajectory ? '展示同化前/后水深；' : '后端仅提供旧概率轨迹；'}
                观测输入 {formatDepthM(astObs)}。{assimData?.provenance || ''}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
