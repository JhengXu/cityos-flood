import { useState, useEffect, useMemo } from 'react'
import { getPredict, getSimulate, fmtTime } from './api'
import Header from './components/Header.jsx'
import CityOverview from './components/CityOverview.jsx'
import RiskMap from './components/RiskMap.jsx'
import RainfallChart from './components/RainfallChart.jsx'
import DistrictPanel from './components/DistrictPanel.jsx'
import ModelInfo from './components/ModelInfo.jsx'
import ScenarioPanel from './components/ScenarioPanel.jsx'
import SimulateChart from './components/SimulateChart.jsx'
import DispatchPanel from './components/DispatchPanel.jsx'
import EventsPanel from './components/EventsPanel.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import OntologyPanel from './components/OntologyPanel.jsx'
import VerifyPanel from './components/VerifyPanel.jsx'
import RolesPanel from './components/RolesPanel.jsx'
import DataLabPanel from './components/DataLabPanel.jsx'
import ModelComparisonPanel from './components/ModelComparisonPanel.jsx'
import PlatformPanel from './components/PlatformPanel.jsx'
import RealDataPanel from './components/RealDataPanel.jsx'
import ProvenancePanel from './components/ProvenancePanel.jsx'
import WorldModelPanel from './components/WorldModelPanel.jsx'

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hour, setHour] = useState(0)
  const [auto, setAuto] = useState(false)

  const [sim, setSim] = useState(null)
  const [simSel, setSimSel] = useState(null)
  const [simLoading, setSimLoading] = useState(false)
  const [verifyKey, setVerifyKey] = useState(0)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const d = await getPredict(3)
      setData(d)
      setHour(0)
    } catch (e) {
      setError(e.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function runSim(params) {
    setSimLoading(true)
    try {
      const r = await getSimulate(params)
      setSim(r)
      setSimSel(r.districts[0].id)
    } catch (e) {
      console.error(e)
    } finally {
      setSimLoading(false)
    }
  }

  useEffect(() => {
    load()
    runSim({ preset: 'typhoon_tide' })
  }, [])

  const view = useMemo(() => {
    if (!data) return null
    return data.districts.map((d) => ({
      ...d,
      at: d.series[Math.min(hour, d.series.length - 1)] || d.current,
    }))
  }, [data, hour])

  useEffect(() => {
    if (!auto || !data) return
    const t = setInterval(() => {
      setHour((h) => (h + 1) % data.hours.length)
    }, 1500)
    return () => clearInterval(t)
  }, [auto, data])

  return (
    <div className="app">
      <Header data={data} onRefresh={load} loading={loading} />
      <nav className="topnav">
        <a href="#overview" className="tn-link">总览</a>
        <a href="#forecast" className="tn-link">预测</a>
        <a href="#research" className="tn-link">研究验证</a>
        <a href="#simulate" className="tn-link">推演决策</a>
        <div className="tn-spacer" />
        <span className="tn-tag">WAM · 深圳内涝</span>
      </nav>
      {error && <div className="error">⚠ {error}</div>}
      {!data && loading && <div className="loading">正在加载城市感知数据…</div>}

      {data && view && (
        <>
          <section id="overview" className="sec-block">
            <CityOverview data={data} view={view} />
          </section>
          <section id="forecast" className="sec-block">

          <div className="timebar">
            <span className="tb-label">时间轴</span>
            <input
              type="range"
              min={0}
              max={data.hours.length - 1}
              value={hour}
              onChange={(e) => setHour(+e.target.value)}
            />
            <span className="tb-time">{fmtTime(data.hours[hour])}</span>
            <button className={`tb-auto ${auto ? 'on' : ''}`} onClick={() => setAuto((a) => !a)}>
              {auto ? '⏸ 暂停推演' : '▶ 自动推演'}
            </button>
          </div>

          <div className="grid">
            <ErrorBoundary
              fallback={
                <div className="card map-wrap">
                  <div className="map-title">深圳市分区分时内涝风险热力</div>
                  <div className="err-box">
                    地图模块加载失败（多为浏览器无法访问地图瓦片 CDN），其余数据功能正常。
                  </div>
                </div>
              }
            >
              <RiskMap data={data} view={view} />
            </ErrorBoundary>
            <div className="col">
              <RainfallChart data={data} hour={hour} setHour={setHour} />
              <DistrictPanel view={view} hour={hour} hours={data.hours} />
            </div>
          </div>

          <ModelInfo data={data} />
          <ProvenancePanel data={data} />
          </section>

          {/* ===== 研究验证演示：WAM 本体 + 可复现验证 + AI 三重角色 ===== */}
          <section id="research" className="research sec-block">
            <div className="section-title">
              研究验证 · 真实数据训练 + 可复现回放 + 量化指标
              <span className="st-sub">城市 3D 本体 → 端到端监督训练 → 三位一体证据</span>
            </div>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">城市本体模块加载失败</div></div>}>
              <OntologyPanel />
            </ErrorBoundary>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">世界行为模型加载失败</div></div>}>
              <WorldModelPanel predictData={data} />
            </ErrorBoundary>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">AI 角色模块加载失败</div></div>}>
              <RolesPanel />
            </ErrorBoundary>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">数据实验室加载失败</div></div>}>
              <DataLabPanel onDataUpdated={() => setVerifyKey((k) => k + 1)} />
            </ErrorBoundary>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">模型对比加载失败</div></div>}>
              <ModelComparisonPanel />
            </ErrorBoundary>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">实时平台数据加载失败</div></div>}>
              <PlatformPanel />
            </ErrorBoundary>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">真实数据态势加载失败</div></div>}>
              <RealDataPanel />
            </ErrorBoundary>
            <ErrorBoundary fallback={<div className="card"><div className="err-box">验证模块加载失败</div></div>}>
              <VerifyPanel key={verifyKey} />
            </ErrorBoundary>
          </section>

          {/* ===== SIMULATE 情景推演 ===== */}
          <section id="simulate" className="simulate sec-block">
            <div className="section-title">
              SIMULATE · 情景推演沙盘
              <span className="st-sub">台风 + 天文大潮 / 泵站降效 / 极端暴雨 → 全城影响推演与处置闭环</span>
            </div>
            <ScenarioPanel onRun={runSim} loading={simLoading} />
            <div className="grid">
              <SimulateChart sim={sim} selected={simSel} onSelect={setSimSel} />
              <DispatchPanel sim={sim} loading={simLoading} />
            </div>
            <EventsPanel />
          </section>
        </>
      )}

      <footer className="foot">
        CITY OS · 深圳城市内涝预测 v2 — 产品型 CEO 黑客松 MVP ｜ 数据：Open-Meteo 多点实时降雨 +
        Open-Elevation 真实高程 + 真实历史内涝事件；城市特征其余项为代表性估算，可替换为权威 GIS/市政数据。
      </footer>
    </div>
  )
}
