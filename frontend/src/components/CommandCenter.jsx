import { useEffect, useState, useRef } from 'react'
import { fetchJSON, fmtTime } from '../api'
import Scene3D from './Scene3D.jsx'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, Legend, BarChart, Bar, Cell } from 'recharts'

/**
 * CommandCenter — 单页指挥中心
 * 一个页面：实时四灾种卡 + 3D 城市场景 + 实时预测曲线 + 关键明细
 * 自动刷新（5 分钟）；数据全部来自 /api/live（Open-Meteo 实时 + 守恒模型 + ML）
 */
const LEVELS = ['正常', '关注', '预警', '危险', '严重']
const LEVEL_COLORS = ['#1f7a4d', '#c9b458', '#e08a1e', '#d6452a', '#b3122b']

export default function CommandCenter() {
  const [live, setLive] = useState(null)
  const [err, setErr] = useState(null)
  const [updatedAt, setUpdatedAt] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const timerRef = useRef(null)

  async function load(force = false) {
    setRefreshing(true)
    try {
      const d = await fetchJSON(force ? '/api/live/refresh' : '/api/live')
      setLive(d)
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN'))
      setErr(null)
    } catch (e) {
      setErr(e.message)
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load(true)
    // 每 5 分钟自动刷新
    timerRef.current = setInterval(() => load(true), 5 * 60 * 1000)
    return () => clearInterval(timerRef.current)
  }, [])

  if (err) return <div className="card"><div className="err-box">⚠ {err}（后端未启动？）</div></div>
  if (!live) return <div className="card"><div className="loading">正在获取实时数据（Open-Meteo + 守恒模型 + ML）…</div></div>

  const { cards, times, city_rain: rain, city_wind: wind, city_flood_series: flood,
          flood_summary: floodTop, landslide_daily: slideDaily, typhoon_now: tyNow } = live

  // 图表数据
  const n = times.length
  const rainChart = times.slice(0, 48).map((t, i) => ({ t: fmtTime(t), 降雨: rain[i] ?? 0 }))
  const floodChart = times.slice(0, 48).map((t, i) => ({ t: fmtTime(t), 积水: flood[i] ?? 0 }))
  const windChart = times.slice(0, 48).map((t, i) => ({ t: fmtTime(t), 风速: wind[i] ?? 0 }))
  const slideChart = slideDaily.map((d) => ({ date: d.date.slice(5), 概率: +(d.warning_prob * 100).toFixed(1), 日降雨: d.rain_24h }))
  const floodBar = floodTop.slice(0, 8).map((f) => ({ name: f.district_name, mm: f.peak_depth_mm }))

  return (
    <div className="cc">
      {/* ===== 顶栏：实时状态 ===== */}
      <div className="cc-topbar">
        <div className="cc-title">
          <b>CITY OS · 深圳全自然灾害指挥中心</b>
          <span className={`cc-src ${live.data_source.includes('realtime') ? 'ok' : 'warn'}`}>
            {live.data_source.includes('realtime') ? '● 实时数据' : '● 回退样本'}
          </span>
          <span className="cc-time">更新 {updatedAt}</span>
        </div>
        <button className="cc-refresh" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? '⟳ 刷新中…' : '⟳ 立即刷新'}
        </button>
      </div>

      {/* ===== 四灾种实时卡 ===== */}
      <div className="hazard-cards">
        {['typhoon', 'flood', 'landslide', 'surge'].map((k) => {
          const c = cards[k]
          const col = LEVEL_COLORS[c.level] || LEVEL_COLORS[0]
          return (
            <div key={k} className={`hazard-card ${k} cc-card`} style={{ borderColor: `${col}55` }}>
              <div className="hc-head">
                <span className="hc-icon">{c.icon}</span>{c.name}
                <span className="cc-lvl" style={{ background: `${col}22`, color: col, borderColor: `${col}66` }}>
                  {LEVELS[c.level]}
                </span>
              </div>
              <div className="hc-big" style={{ color: col }}>{c.value}</div>
              <div className="hc-sub">{c.sub}</div>
              <div className="cc-extra">
                {k === 'typhoon' && <span>活跃台风：<b style={{ color: tyNow ? '#e08a1e' : '#7ee2a8' }}>{tyNow ? `${tyNow.name}（${tyNow.wind_ms}m/s）` : '无'}</b></span>}
                {k === 'flood' && <span>最不利区：<b>{c.worst}</b></span>}
                {k === 'landslide' && <span>隐患点：<b>{c.points}</b> 个</span>}
                {k === 'surge' && <span>潮位站：<b>{c.stations}</b> 个</span>}
              </div>
            </div>
          )
        })}
      </div>

      {/* ===== 3D 城市场景（台风活跃时叠加路径由独立按钮触发）===== */}
      <div className="card cc-3dcard">
        <div className="map-title">深圳 3D 城市实景 · 地形 + 建筑 + 四大灾种点位
          <span className="cc-3dhint">拖拽旋转 · 滚轮缩放</span>
        </div>
        <Scene3D height={430} />
      </div>

      {/* ===== 实时预测曲线（三联）===== */}
      <div className="cc-charts">
        <div className="card cc-chart">
          <div className="cascade-subtitle">实时降雨预报（Open-Meteo，未来 48h，mm/h）</div>
          <ResponsiveContainer width="100%" height={210}>
            <AreaChart data={rainChart}>
              <XAxis dataKey="t" stroke="#9ab" interval={5} />
              <YAxis stroke="#9ab" unit="mm" />
              <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
              <Area dataKey="降雨" stroke="#4da3ff" fill="#4da3ff33" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="card cc-chart">
          <div className="cascade-subtitle">内涝预测 · 全城峰值积水（守恒模型，mm）</div>
          <ResponsiveContainer width="100%" height={210}>
            <AreaChart data={floodChart}>
              <XAxis dataKey="t" stroke="#9ab" interval={5} />
              <YAxis stroke="#9ab" unit="mm" />
              <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
              <Area dataKey="积水" stroke="#e08a1e" fill="#e08a1e33" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="card cc-chart">
          <div className="cascade-subtitle">风速预报（m/s）</div>
          <ResponsiveContainer width="100%" height={210}>
            <AreaChart data={windChart}>
              <XAxis dataKey="t" stroke="#9ab" interval={5} />
              <YAxis stroke="#9ab" unit="m/s" />
              <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
              <Area dataKey="风速" stroke="#37c8c3" fill="#37c8c333" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ===== 滑坡 ML 预测 + 内涝分区 TOP ===== */}
      <div className="grid-2col" style={{ paddingTop: 0 }}>
        <div className="card">
          <div className="cascade-subtitle">⛰ 滑坡预警概率（ML 模型 · 905 条官方预警训练）</div>
          {slideChart.length > 0 ? (
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={slideChart}>
                <XAxis dataKey="date" stroke="#9ab" />
                <YAxis stroke="#9ab" unit="%" domain={[0, 100]} />
                <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="概率" type="monotone" stroke="#d6452a" strokeWidth={2} dot={{ r: 3 }} />
                <Line dataKey="日降雨" type="monotone" stroke="#4da3ff" strokeWidth={1.5} dot={false} yAxisId={0} />
              </LineChart>
            </ResponsiveContainer>
          ) : <div className="footnote">暂无预报降雨数据</div>}
          <div className="footnote">模型验证：时间外 AUC=0.813（2013-2022 训练 → 2023-2026 测试）</div>
        </div>
        <div className="card">
          <div className="cascade-subtitle">🌧️ 内涝分区峰值 TOP（守恒模型，mm）</div>
          {floodBar.length > 0 ? (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={floodBar} layout="vertical" margin={{ left: 40 }}>
                <XAxis type="number" stroke="#9ab" unit="mm" />
                <YAxis type="category" dataKey="name" stroke="#9ab" width={62} />
                <Tooltip contentStyle={{ background: '#16202e', border: '1px solid #2a3a4e' }} />
                <Bar dataKey="mm" radius={[0, 5, 5, 0]}>
                  {floodBar.map((f, i) => (
                    <Cell key={i} fill={f.mm >= 100 ? '#b3122b' : f.mm >= 40 ? '#d6452a' : f.mm >= 15 ? '#e08a1e' : '#c9b458'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <div className="footnote">暂无数据</div>}
          <div className="footnote">守恒状态空间模型 · 真实 GIS 参数 · 质量守恒可审计</div>
        </div>
      </div>

      {/* ===== 数据来源（诚实标注）===== */}
      <div className="cc-prov">
        {Object.entries(live.provenance || {}).map(([k, v]) => (
          <span key={k} className="prov-chip"><b>{k}</b> {v}</span>
        ))}
        <span className="prov-chip auto">每 5 分钟自动刷新 · 研究演示原型，不替代正式预警</span>
      </div>
    </div>
  )
}
