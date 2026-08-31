import { useEffect, useState, useRef, useMemo } from 'react'
import { fetchJSON, fmtTime, getTyphoonTrack } from '../api'
import Scene3D from './Scene3D.jsx'
import SurgePanel from './SurgePanel.jsx'
import WhatIfPanel from './WhatIfPanel.jsx'
import RiskMap from './RiskMap.jsx'
import AnimatedNumber from './AnimatedNumber.jsx'
import AlertStream from './AlertStream.jsx'
import FloodRiskPanel from './FloodRiskPanel.jsx'
import DailyBriefing from './DailyBriefing.jsx'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend, BarChart, Bar, Cell, CartesianGrid,
  ReferenceLine,
} from 'recharts'

/**
 * OverviewPage — 态势总览（v5 重构）
 * 四灾种实时卡 + 3D 城市实景 + 三联预测曲线 + 滑坡概率 + 内涝分区
 */
// 后端等级语义（live_ops.py）：1=正常 2=关注 3=预警 4=危险 → 索引对齐
const LEVELS = { 1: '正常', 2: '关注', 3: '预警', 4: '危险' }
const LEVEL_COLORS = { 1: '#34d399', 2: '#fbbf24', 3: '#f59e0b', 4: '#ff6b5e' }

const TIP = { background: 'var(--chart-tip-bg)', border: '1px solid var(--chart-tip-border)', borderRadius: 8, fontSize: 12, color: 'var(--ink)' }
const AXIS = { stroke: 'var(--chart-text)', fontSize: 11 }

export default function OverviewPage({ predictData = null }) {
  const [live, setLive] = useState(null)
  const [err, setErr] = useState(null)
  const [updatedAt, setUpdatedAt] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [tyTrack, setTyTrack] = useState(null)
  const [viewMode, setViewMode] = useState('3d')
  const timerRef = useRef(null)

  async function load(force = false) {
    setRefreshing(true)
    try {
      const d = await fetchJSON(force ? '/api/live/refresh' : '/api/live')
      setLive(d)
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
      setErr(null)
    } catch (e) {
      setErr(e.message)
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load(true)
    timerRef.current = setInterval(() => load(true), 5 * 60 * 1000)
    // SSE 告警变化 → 立即刷新（不用等 5 分钟轮询）
    const onAlerts = () => load(false)
    window.addEventListener('cityos:alerts-updated', onAlerts)
    return () => {
      clearInterval(timerRef.current)
      window.removeEventListener('cityos:alerts-updated', onAlerts)
    }
  }, [])

  // 活跃台风 → 3D 路径叠加
  useEffect(() => {
    fetchJSON('/api/live').then((d) => {
      const ty = d?.typhoon_now
      if (ty?.name) {
        getTyphoonTrack(ty.name).then((r) => {
          const pts = (r?.points || []).filter((p) => p.lat && p.lon)
          if (pts.length > 1) setTyTrack(pts)
        }).catch(() => {})
      }
    }).catch(() => {})
  }, [])

  if (err) return <div className="err-box">⚠ {err}（后端未启动？）</div>
  if (!live) return <div className="card"><div className="loading">正在获取实时数据（Open-Meteo + 守恒模型 + ML）…</div></div>

  const { cards, times, city_rain: rain, city_wind: wind, city_flood_series: flood,
          flood_summary: floodTop, landslide_daily: slideDaily, typhoon_now: tyNow,
          current: cur, now_idx: nowIdx, next_24h: next24 } = live

  const i0 = Math.max(0, nowIdx - 6) // 从 6 小时前开始（背景）
  const nShow = 48
  const rainChart = times.slice(i0, i0 + nShow).map((t, i) => ({ t: fmtTime(t), 降雨: rain[i0 + i] ?? 0 }))
  const floodChart = times.slice(i0, i0 + nShow).map((t, i) => ({ t: fmtTime(t), 积水: flood[i0 + i] ?? 0 }))
  const windChart = times.slice(i0, i0 + nShow).map((t, i) => ({ t: fmtTime(t), 风速: wind[i0 + i] ?? 0 }))
  const nowOffset = nowIdx - i0 // 「现在」在图表内的位置
  const slideChart = slideDaily.map((d) => ({ date: d.date.slice(5), 概率: +(d.warning_prob * 100).toFixed(1), 日降雨: d.rain_24h }))
  const floodBar = floodTop.slice(0, 8).map((f) => ({ name: f.district_name, mm: f.peak_depth_mm }))

  // 未来 24h 峰值雨强（从"现在"起算，来自后端 next_24h）
  const rainPeak = next24?.rain_max_mm_h ?? 0
  const rainNext24 = next24?.rain_total_mm ?? 0
  const curRain = cur?.precipitation_mm
  const isRaining = (curRain ?? 0) >= 0.1

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 1500 }}>
      {/* ===== 刷新条 ===== */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span className={`chip ${isRaining ? 'warn' : 'ok'}`}>
          {isRaining ? `🌧 实况降雨 ${curRain.toFixed(1)} mm/h` : '☀ 当前无降雨'}
          {cur?.temperature_2m != null && ` · ${cur.temperature_2m.toFixed(0)}°C`}
        </span>
        <span className="chip ok">● {live.data_source.includes('realtime') ? 'Open-Meteo 实时' : '回退样本'}</span>
        <span className="chip">更新 {updatedAt}</span>
        {(live.advance_warnings || []).filter(w => w.warning_prob >= 0.3).map(w => (
          <span key={w.for_date} className="chip warn">
            ⏰ D-1 预警：{w.for_date.slice(5)} 滑坡概率 {w.warning_prob.toFixed(0)}%
          </span>
        ))}
        {rainPeak > 5 && <span className="chip warn">未来 24h 降雨 {rainNext24.toFixed(1)}mm（峰值 {rainPeak.toFixed(1)} mm/h）</span>}
        <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? '⟳ 刷新中…' : '⟳ 立即刷新'}
        </button>
      </div>

      {/* ===== 内涝概率桶 ===== */}
      <FloodRiskPanel />

      {/* ===== 今日态势简报 ===== */}
      <DailyBriefing />

      {/* ===== 实时告警流 ===== */}
      <AlertStream alerts={live.alerts || []} generatedAt={live.generated_at || ''} />

      {/* ===== 四灾种实时卡 ===== */}
      <div className="ov-grid">
        {['typhoon', 'flood', 'landslide', 'surge'].map((k) => {
          const c = cards[k]
          const col = LEVEL_COLORS[c.level] || LEVEL_COLORS[1]
          return (
            <div key={k} className="hazard-card" style={{ '--hc-color': col }}>
              <div className="hc-top">
                <span className="hc-icon">{c.icon}</span>
                <span className="hc-name">{c.name}</span>
                <span className="hc-level">{LEVELS[c.level]}</span>
              </div>
              <div className="hc-value stat-num">
                {k === 'typhoon' && cur?.wind_speed_10m != null
                  ? <AnimatedNumber value={cur.wind_speed_10m} format={(v) => v.toFixed(0)} />
                  : (() => {
                      const m = String(c.value).match(/^([\d.]+)\s*(.*)$/)
                      if (m) return <><AnimatedNumber value={parseFloat(m[1])} format={(v) => (Number.isInteger(parseFloat(m[1])) ? v.toFixed(0) : v.toFixed(1))} /> {m[2]}</>
                      return c.value
                    })()}
              </div>
              <div className="hc-sub">{k === 'typhoon' ? '当前实测风速' : c.sub}</div>
              <div className="hc-extra">
                {k === 'typhoon' && <><span>活跃台风</span><b>{tyNow ? `${tyNow.name} ${tyNow.wind_ms}m/s` : '无'}</b></>}
                {k === 'flood' && <><span>最不利区</span><b>{c.worst}</b></>}
                {k === 'landslide' && <><span>隐患点</span><b>{c.points} 个</b></>}
                {k === 'surge' && <><span>增水估计</span><b>{c.surge_m != null ? `+${c.surge_m.toFixed(2)} m` : '—'}</b></>}
              </div>
            </div>
          )
        })}
      </div>

      {/* ===== 主区：3D + 三联曲线 ===== */}
      <div className="ov-main">
        <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div className="card-h">
            {viewMode === '3d' ? '🏙 深圳 3D 城市实景' : '🗺️ 深圳内涝风险地图（2D）'}
            <span style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
              <button className={`btn sm ${viewMode === '2d' ? 'primary' : ''}`} onClick={() => setViewMode('2d')}>2D 地图</button>
              <button className={`btn sm ${viewMode === '3d' ? 'primary' : ''}`} onClick={() => setViewMode('3d')}>3D 实景</button>
            </span>
          </div>
          <div style={{ flex: 1, minHeight: 420 }}>
            {viewMode === '3d' ? (
              <Scene3D height={430} typhoonTrack={tyTrack} alertLevel={live.cards?.surge?.level || 0} />
            ) : predictData ? (
              <RiskMap2D predictData={predictData} />
            ) : (
              <div className="loading">加载预测数据…</div>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <MiniChartCard title="🌧️ 降雨（过去 6h + 未来 48h）" hint={isRaining ? `实况 ${curRain.toFixed(1)} mm/h` : '当前无降雨'} data={rainChart} color="#3d8bff" unit="mm" nowIdx={nowOffset} />
          <MiniChartCard title="🌊 内涝预测 · 全城峰值" hint="守恒模型 · mm" data={floodChart} color="#f59e0b" unit="mm" nowIdx={nowOffset} />
          <MiniChartCard title="💨 风速" hint="m/s" data={windChart} color="#2fd4c8" unit="m/s" nowIdx={nowOffset} />
        </div>
      </div>

      {/* ===== 第三行：滑坡 ML + 内涝分区 ===== */}
      <div className="ov-row3">
        <div className="card" style={{ gridColumn: 'span 2' }}>
          <div className="card-h">
            ⛰ 滑坡预警概率日演进
            <span className="hint">ML 模型 · 905 条官方预警训练 · 时间外 AUC=0.821 · 召回率 36%（保守口径）</span>
          </div>
          <div className="chart-body" style={{ height: 240 }}>
            {slideChart.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={slideChart} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" {...AXIS} tickLine={false} axisLine={false} />
                  <YAxis {...AXIS} unit="%" domain={[0, 100]} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line dataKey="概率" type="monotone" stroke="#ff6b5e" strokeWidth={2.2} dot={{ r: 3, fill: '#ff6b5e' }} />
                  <Line dataKey="日降雨" type="monotone" stroke="#3d8bff" strokeWidth={1.6} dot={false} strokeDasharray="4 3" />
                </LineChart>
              </ResponsiveContainer>
            ) : <div className="footnote" style={{ padding: 14 }}>暂无预报降雨数据</div>}
          </div>
        </div>
        <div className="card">
          <div className="card-h">
            🌧️ 内涝分区峰值 TOP
            <span className="hint">守恒模型 · mm</span>
          </div>
          <div className="chart-body" style={{ height: 240 }}>
            {floodBar.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={floodBar} layout="vertical" margin={{ top: 4, right: 18, bottom: 0, left: 8 }}>
                  <XAxis type="number" {...AXIS} unit="mm" tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="name" {...AXIS} width={56} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={TIP} cursor={{ fill: 'var(--line-soft)' }} />
                  <Bar dataKey="mm" radius={[0, 5, 5, 0]} barSize={14}>
                    {floodBar.map((f, i) => (
                      <Cell key={i} fill={f.mm >= 100 ? '#ff4757' : f.mm >= 40 ? '#ff6b5e' : f.mm >= 15 ? '#f59e0b' : '#fbbf24'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="footnote" style={{ padding: 14 }}>暂无数据</div>}
          </div>
        </div>
      </div>

      {/* ===== 风暴潮面板 ===== */}
      <SurgePanel />

      {/* ===== 台风 What-if 推演 ===== */}
      <WhatIfPanel />

      {/* ===== 数据来源与模型口径（全链路标注） ===== */}
      <DataSources live={live} />
    </div>
  )
}


function MiniChartCard({ title, hint, data, color, unit, nowIdx }) {
  return (
    <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div className="chart-title">{title}<span className="hint">{hint}</span></div>
      <div style={{ flex: 1, padding: '4px 8px 8px', minHeight: 118 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
            <defs>
              <linearGradient id={`g-${title.length}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <XAxis dataKey="t" {...AXIS} interval="preserveStartEnd" tickLine={false} axisLine={false} minTickGap={40} />
            <YAxis {...AXIS} unit={unit} tickLine={false} axisLine={false} width={44} />
            <Tooltip contentStyle={TIP} />
            {nowIdx != null && nowIdx > 0 && nowIdx < data.length && (
              <ReferenceLine x={data[nowIdx]?.t} stroke="var(--warn)" strokeDasharray="4 3" label={{ value: '现在', position: 'insideTopLeft', fontSize: 9, fill: 'var(--warn)' }} />
            )}
            <Area dataKey={Object.keys(data[0] || { a: 1 }).find(k => k !== 't')} type="monotone" stroke={color} strokeWidth={2} fill={`url(#g-${title.length})`} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}


/* ================= 数据来源与模型口径 ================= */

const SOURCE_TABLE = [
  { group: '实时气象', items: [
    ['当前实况（温度/雨/风）', 'Open-Meteo current 实测接口', 'observed'],
    ['降雨/风速预报（48h）', 'Open-Meteo hourly（过去 6h + 未来 48h）', 'predicted'],
  ]},
  { group: '台风', items: [
    ['活跃台风（位置/强度）', '气象局台风预报表（typhoon_forecast）', 'forecast'],
    ['历史路径（42 个事件）', 'IBTrACS v04r01 (2014-2026)', 'observed'],
  ]},
  { group: '内涝预测', items: [
    ['积水深度（逐时/分区）', '守恒状态空间模型（真实 GIS 参数，质量守恒可审计）', 'model'],
    ['易涝点底数（206 处）', '官方 2019 易涝路段名单（天地图地理编码）', 'observed'],
  ]},
  { group: '滑坡预警', items: [
    ['预警概率（日）', '监督模型：905 条官方预警训练，时间外 AUC=0.821 · 召回率 36%（保守口径）', 'model'],
    ['隐患点（300 处）', '深圳市规划和自然资源局 2023 在册', 'observed'],
    ['训练特征（2013-2026）', 'ERA5-Land 逐日（免账号下载）', 'reanalysis'],
  ]},
  { group: '风暴潮', items: [
    ['天文潮（逐时推算）', 'HKO 3 年逐时数据拟合 8 分潮谐波（RMSE 0.13m）', 'model'],
    ['台风增水', '气压反效应 + 风堆积参数化（量级估计，非数值模式）', 'model'],
    ['波浪（历史事件）', 'CMEMS WAVERYS 再分析（卫星高度计同化）', 'reanalysis'],
    ['潮位站基准', '香港天文台 CD 海图基准', 'observed'],
  ]},
  { group: '城市底座', items: [
    ['人口（1163/1697 万）', 'WorldPop 100m/1km 栅格（点入多边形聚合）', 'dataset'],
    ['建筑（87,495 栋）', 'OSM 全市建筑足迹（含高度估计）', 'dataset'],
    ['地形（-19~937m）', 'Copernicus DEM 30m', 'dataset'],
    ['土地覆盖', 'ESA WorldCover 10m 2021', 'dataset'],
  ]},
]

const TYPE_LABEL = {
  observed: { t: '实测', c: 'var(--ok)' },
  predicted: { t: '预报', c: 'var(--accent)' },
  forecast: { t: '预报', c: 'var(--accent)' },
  model: { t: '模型', c: 'var(--purple)' },
  reanalysis: { t: '再分析', c: 'var(--warn)' },
  dataset: { t: '数据集', c: 'var(--ink-3)' },
}

function DataSources({ live }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card">
      <button
        onClick={() => setOpen(o => !o)}
        style={{ all: 'unset', cursor: 'pointer', width: '100%', padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 8 }}
      >
        <b style={{ fontSize: 13 }}>📋 数据来源与模型口径（全链路）</b>
        <span className="chip" style={{ marginLeft: 'auto' }}>{open ? '收起 ▲' : '展开 ▼'}</span>
      </button>
      {open && (
        <div style={{ padding: '0 16px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {SOURCE_TABLE.map(g => (
            <div key={g.group}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink-2)', marginBottom: 4 }}>{g.group}</div>
              {g.items.map(([name, src, type]) => {
                const tl = TYPE_LABEL[type] || TYPE_LABEL.dataset
                return (
                  <div key={name} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 11.5, padding: '2px 0', flexWrap: 'wrap' }}>
                    <span style={{ color: 'var(--ink-3)', minWidth: 140 }}>{name}</span>
                    <span style={{ color: 'var(--ink-2)', flex: 1 }}>{src}</span>
                    <span className="chip" style={{ color: tl.c, borderColor: `color-mix(in srgb, ${tl.c} 35%, transparent)`, fontSize: 9, padding: '0 7px' }}>{tl.t}</span>
                  </div>
                )
              })}
            </div>
          ))}
          <div style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 8 }}>
            <p className="footnote">
              模型口径声明：内涝概率与滑坡概率为本项目研究模型输出，<b>不替代官方预警</b>；
              风暴潮增水为参数化量级估计；ML 指标均为防泄漏验证（时间外/空间分块/留一事件）。
              每 5 分钟自动刷新。
            </p>
          </div>
        </div>
      )}
    </div>
  )
}


/* ================= 2D 风险地图（适配 v4 predict 结构） ================= */

function RiskMap2D({ predictData }) {
  // v4 predict: districts[].series[hour] 是时次点；RiskMap 期望 district.at
  const adapted = useMemo(() => {
    if (!predictData) return null
    return {
      ...predictData,
      districts: (predictData.districts || []).map((d) => ({
        ...d,
        at: d.series?.[0] || d.peak || {},
      })),
    }
  }, [predictData])
  if (!adapted) return <div className="loading">加载预测数据…</div>
  return <RiskMap data={adapted} view={adapted.districts} hour={0} />
}
