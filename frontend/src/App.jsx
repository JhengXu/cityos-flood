import { useState, useEffect, useMemo, useRef, createContext, useContext } from 'react'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import OverviewPage from './components/OverviewPage.jsx'
import WorldModelPage from './components/WorldModelPage.jsx'
import OptimizationPage from './components/OptimizationPage.jsx'
import KnowledgeBasePanel from './components/KnowledgeBasePanel.jsx'
import TyphoonPage from './components/TyphoonPage.jsx'
import SurgePage from './components/SurgePage.jsx'
import LandslidePage from './components/LandslidePage.jsx'
import { getPredict } from './api'

/* ============ 主题上下文 ============ */
const ThemeCtx = createContext({ theme: 'dark', toggle: () => {} })
export const useTheme = () => useContext(ThemeCtx)

/* ============ 时钟 ============ */
function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

/* ============ 导航结构 ============ */
const NAV = [
  {
    section: '指挥',
    items: [
      { id: 'overview', icon: '◎', label: '态势总览', desc: '四灾种实时 · 3D 城市 · 预测曲线' },
    ],
  },
  {
    section: '世界模型',
    items: [
      { id: 'world', icon: '◈', label: '推演与反事实', desc: '空间耦合 · 可达性 · 同化' },
      { id: 'wam', icon: '⬢', label: '自主优化 WAM', desc: 'CEM 安全决策闭环' },
    ],
  },
  {
    section: '知识',
    items: [
      { id: 'knowledge', icon: '▤', label: '沉淀知识库', desc: '案例沉淀 · 城安助手 RAG' },
    ],
  },
  {
    section: '灾种专页',
    items: [
      { id: 'typhoon', icon: '🌀', label: '台风', desc: '路径库 · 链式预测 · 3D 叠加' },
      { id: 'surge', icon: '🌊', label: '风暴潮', desc: '潮位站 · 波浪事件 · 海洋点位' },
      { id: 'landslide', icon: '⛰', label: '滑坡', desc: '隐患点 · 分区风险' },
    ],
  },
]

const PAGE_TITLES = {
  overview: { title: '态势总览', sub: '四灾种实时状态 · Open-Meteo 预报 + 守恒模型 + ML' },
  world: { title: '世界模型推演', sub: '空间耦合 · 可达性 · 反事实 · 数据同化' },
  wam: { title: '自主优化 WAM', sub: 'CEM 安全决策闭环 · 建议式输出（不下发 SCADA）' },
  knowledge: { title: '沉淀知识库', sub: '真实事件案例 · 城安助手 RAG 问答 · 城市底座' },
  typhoon: { title: '台风灾害', sub: '历史路径库 · 多灾种链式预测 · 3D 路径叠加' },
  surge: { title: '风暴潮灾害', sub: '潮位站统计 · 四大事件波浪 · 历史档案' },
  landslide: { title: '滑坡灾害', sub: '在册隐患点 · 分区风险 · 官方预警模型' },
}

export default function App() {
  const [page, setPage] = useState('overview')
  const [collapsed, setCollapsed] = useState(false)
  const [theme, setTheme] = useState(() => localStorage.getItem('cityos-theme') || 'dark')
  const [predict, setPredict] = useState(null)
  const [liveStatus, setLiveStatus] = useState(null)
  const now = useClock()

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('cityos-theme', theme)
  }, [theme])

  useEffect(() => {
    getPredict(3).then(setPredict).catch(() => setPredict(null))
    fetch('/api/live').then(r => r.json()).then(d => setLiveStatus(d)).catch(() => setLiveStatus(null))
  }, [])

  const themeApi = useMemo(() => ({
    theme,
    toggle: () => setTheme(t => t === 'dark' ? 'light' : 'dark'),
  }), [theme])

  const isLive = String(liveStatus?.data_source || '').includes('realtime')

  return (
    <ThemeCtx.Provider value={themeApi}>
      <div className={`shell ${collapsed ? 'collapsed' : ''}`}>
        {/* ===== 顶栏 ===== */}
        <header className="topbar">
          <button className="icon-btn" onClick={() => setCollapsed(c => !c)} title="收起/展开侧栏">
            {collapsed ? '»' : '«'}
          </button>
          <div className="topbar-brand">
            <span className="brand-mark">C</span>
            <div className="brand-text">
              <b>CITY OS</b>
              <span>深圳全自然灾害指挥中心 v5</span>
            </div>
          </div>
          <div className="topbar-live">
            <span className={`live-dot ${isLive ? '' : 'off'}`} />
            {isLive ? '实时数据在线' : '回退样本'}
            {liveStatus?.typhoon_now && (
              <span className="chip warn" style={{ marginLeft: 6 }}>🌀 {liveStatus.typhoon_now.name}</span>
            )}
          </div>
          <div className="topbar-clock">
            <div style={{ textAlign: 'right' }}>
              <div className="clock-time">{now.toLocaleTimeString('zh-CN', { hour12: false })}</div>
              <div className="clock-date">{now.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' })}</div>
            </div>
            <button className="icon-btn" onClick={themeApi.toggle} title="切换深浅主题">
              {theme === 'dark' ? '☀' : '☾'}
            </button>
          </div>
        </header>

        {/* ===== 侧边导航 ===== */}
        <nav className="sidebar">
          {NAV.map(sec => (
            <div key={sec.section} className="side-section">
              <div className="side-label">{sec.section}</div>
              {sec.items.map(it => (
                <button
                  key={it.id}
                  className={`nav-item ${page === it.id ? 'on' : ''}`}
                  onClick={() => setPage(it.id)}
                  title={it.desc}
                >
                  <span className="nav-icon">{it.icon}</span>
                  <span className="nav-text">{it.label}</span>
                </button>
              ))}
            </div>
          ))}
          <div className="side-foot">
            守恒状态空间 + 本体脆弱性<br />+ 反事实 + EnSRF + CEM<br /><br />
            <span style={{ opacity: 0.7 }}>研究演示原型<br />不替代正式预警</span>
          </div>
        </nav>

        {/* ===== 内容区 ===== */}
        <main className="content">
          <div className="page-head">
            <div className="page-title">
              <h1>{PAGE_TITLES[page].title}</h1>
              <p>{PAGE_TITLES[page].sub}</p>
            </div>
          </div>
          <div className="page-enter" key={page}>
            <ErrorBoundary fallback={<div className="err-box">模块加载失败</div>}>
              {page === 'overview' && <OverviewPage predictData={predict} />}
              {page === 'world' && <WorldModelPage predictData={predict} />}
              {page === 'wam' && <OptimizationPage predictData={predict} />}
              {page === 'knowledge' && <KnowledgeBasePanel />}
              {page === 'typhoon' && <div className="legacy-wrap"><TyphoonPage /></div>}
              {page === 'surge' && <div className="legacy-wrap"><SurgePage /></div>}
              {page === 'landslide' && <div className="legacy-wrap"><LandslidePage /></div>}
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </ThemeCtx.Provider>
  )
}
