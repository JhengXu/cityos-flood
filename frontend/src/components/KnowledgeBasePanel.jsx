import { useEffect, useState, useMemo, useRef } from 'react'
import { fetchJSON } from '../api'
import FloodProfilePanel from './FloodProfilePanel.jsx'

/**
 * KnowledgeBasePanel — 沉淀知识库（参照 cityos-command-workbench 设计）
 * 双 Tab：城安助手（RAG 问答）+ 案例沉淀（真实事件档案）
 * 附加：城市底座统计 + 模型档案
 *
 * 数据全部来自 /api/knowledge/*（后端 knowledge.py，真实数据驱动）
 */
export default function KnowledgeBasePanel() {
  const [tab, setTab] = useState('cases') // cases | assistant | base | models

  const TABS = [
    { id: 'cases', label: '案例沉淀', icon: '📚', desc: '6 个真实事件档案 + 模型回放' },
    { id: 'events', label: '历史事件', icon: '🗓️', desc: '公开报道的真实内涝事件库' },
    { id: 'assistant', label: '城安助手', icon: '🤖', desc: '基于案例库的检索问答' },
    { id: 'base', label: '城市底座', icon: '🏙️', desc: '人口/建筑/地形/暴露统计' },
    { id: 'models', label: '模型档案', icon: '🧪', desc: '三个监督模型指标与局限' },
  ]

  return (
    <div className="kb-root">
      <div className="kb-header">
        <div className="kb-title">
          <b>沉淀知识库</b>
          <span className="kb-sub">真实事件案例 · 模型回放 · 城市底座 —— 数据全部来自统一数据层</span>
        </div>
        <div className="kb-tabs">
          {TABS.map((t) => (
            <button key={t.id} className={`kb-tab ${tab === t.id ? 'on' : ''}`} onClick={() => setTab(t.id)} title={t.desc}>
              <span>{t.icon}</span>{t.label}
            </button>
          ))}
        </div>
      </div>
      {tab === 'cases' && <CasesTab />}
      {tab === 'events' && <EventsTab />}
      {tab === 'assistant' && <AssistantTab />}
      {tab === 'base' && <CityBaseTab />}
      {tab === 'models' && <ModelsTab />}
    </div>
  )
}


/* ============================== 案例沉淀 ============================== */

function CasesTab() {
  const [list, setList] = useState(null)
  const [detail, setDetail] = useState(null)
  const [domain, setDomain] = useState('')
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)

  async function load(d = domain, query = q) {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (d) params.set('domain', d)
      if (query) params.set('q', query)
      const r = await fetchJSON(`/api/knowledge/cases?${params}`)
      setList(r)
    } catch (e) {
      setList({ error: e.message })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function openCase(id) {
    try {
      const r = await fetchJSON(`/api/knowledge/cases/${id}`)
      setDetail(r)
    } catch (e) {
      setDetail({ error: e.message })
    }
  }

  if (!list) return <div className="card"><div className="loading">加载知识库案例…</div></div>
  if (list.error) return <div className="card"><div className="err-box">⚠ {list.error}</div></div>

  return (
    <div className="kb-cases">
      {/* 筛选栏 */}
      <div className="kb-filter">
        <input
          className="kb-search" placeholder="检索案例（如：山竹 / 暴雨 / 洪水）"
          value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
        />
        <select className="kb-select" value={domain} onChange={(e) => { setDomain(e.target.value); load(e.target.value, q) }}>
          <option value="">全部领域</option>
          {(list.domains || []).map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <div className="kb-count">
          <span>{list.total} 条案例</span>
          <span className="kb-ok">{list.demo_active} 条演示在用</span>
        </div>
      </div>

      <div className="kb-split">
        {/* 案例列表 */}
        <div className="kb-list">
          {(list.cases || []).map((c) => (
            <button key={c.id} className={`kb-case-item ${detail?.id === c.id ? 'on' : ''}`} onClick={() => openCase(c.id)}>
              <div className="kb-case-head">
                <span className="kb-domain" style={{ background: `${c.domain_color}22`, color: c.domain_color, borderColor: `${c.domain_color}55` }}>
                  {c.icon} {c.domain_label}
                </span>
                <span className="kb-date">{c.occurred_at}</span>
              </div>
              <div className="kb-case-title">{c.title}</div>
              <div className="kb-case-summary">{c.summary}</div>
              <div className="kb-case-badges">
                {c.model_prob != null && (
                  <span className={`kb-badge ${c.model_prob >= 0.9 ? 'hot' : c.model_prob >= 0.5 ? 'warm' : ''}`}>
                    模型 {(c.model_prob * 100).toFixed(0)}%
                  </span>
                )}
                <span className="kb-badge">官方 {c.official_level}</span>
                {c.usage === 'demo-active' && <span className="kb-badge ok">演示在用</span>}
              </div>
            </button>
          ))}
          {list.cases?.length === 0 && <div className="kb-empty">没有匹配的案例</div>}
        </div>

        {/* 案例详情 */}
        <div className="kb-detail">
          {detail ? <CaseDetail c={detail} onAsk={(t) => { /* 切到助手 */ }} /> : (
            <div className="kb-empty-big">
              <div>📋</div>
              <p>选择左侧案例查看完整档案</p>
              <p className="kb-hint">每个案例 = 当时已知（真实观测）+ 关键未知项 + 模型回放（ML 概率时间线）</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


function CaseDetail({ c }) {
  const probColor = (p) => p >= 0.9 ? '#d6452a' : p >= 0.5 ? '#e08a1e' : '#1f7a4d'
  return (
    <div className="kb-case-detail">
      <div className="kb-detail-head">
        {c.domain === 'typhoon' && (
          <button
            className="btn sm"
            style={{ position: 'absolute', right: 14, top: 60, zIndex: 2 }}
            onClick={() => {
              sessionStorage.setItem('kb-prefill', `${c.title}的灾害链是什么？`)
              ;[...document.querySelectorAll('.nav-item')].find((b) => b.textContent.includes('态势总览'))?.click()
            }}
            title="跳转到态势总览的 What-if 推演面板"
          >
            🌀 What-if 推演
          </button>
        )}
        <div className="kb-detail-meta">
          <span className="kb-domain" style={{ background: `${c.domain_color}22`, color: c.domain_color, borderColor: `${c.domain_color}55` }}>
            {c.icon} {c.domain_label}
          </span>
          <span className="kb-date">{c.occurred_at}</span>
          <span className="kb-loc">📍 {c.location}</span>
        </div>
        <h3>{c.title}</h3>
      </div>

      {/* 三段核心：当时已知 / 关键未知 / 模型复盘 */}
      <div className="kb-tri">
        <div className="kb-block ok">
          <div className="kb-block-title">✅ 当时已知（真实观测）</div>
          <p>{c.facts}</p>
        </div>
        <div className="kb-block warn">
          <div className="kb-block-title">⚠️ 关键未知项</div>
          <p>{c.unknowns}</p>
        </div>
        <div className="kb-block info">
          <div className="kb-block-title">🧠 模型回放</div>
          <p>{c.replay?.summary}</p>
        </div>
      </div>

      {/* 模型概率 vs 官方预警时间线 */}
      {c.replay?.daily && (
        <div className="kb-replay">
          <div className="kb-block-title">📈 模型概率 vs 官方预警 · 日序列</div>
          <div className="kb-replay-rows">
            {c.replay.daily.map((d) => (
              <div key={d.date} className="kb-replay-row">
                <span className="kb-replay-date">{d.date}</span>
                <div className="kb-replay-bar">
                  <div className="kb-replay-fill" style={{ width: `${(d.prob * 100).toFixed(1)}%`, background: probColor(d.prob) }} />
                </div>
                <span className="kb-replay-prob" style={{ color: probColor(d.prob) }}>{(d.prob * 100).toFixed(1)}%</span>
                <span className="kb-replay-note">{d.note}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 关键指标 */}
      {c.metrics && (
        <div className="kb-metrics">
          <div className="kb-block-title">📊 关键指标（真实数据）</div>
          <div className="kb-metrics-grid">
            {Object.entries(c.metrics).map(([k, v]) => (
              <div key={k} className="kb-metric">
                <span className="kb-metric-k">{METRIC_LABELS[k] || k}</span>
                <span className="kb-metric-v">{formatMetric(v, k)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 可复用经验 */}
      <div className="kb-block lesson">
        <div className="kb-block-title">💡 可复用经验</div>
        <p>{c.lesson}</p>
      </div>

      {/* 来源 */}
      <div className="kb-sources">
        <div className="kb-block-title">🔗 关联来源</div>
        <div className="kb-source-chips">
          {(c.sources || []).map((s) => <span key={s} className="kb-chip">{s}</span>)}
        </div>
        <p className="kb-disclaimer">来源为条目级关联；案例档案为研究复盘口径，不代表官方调度记录。</p>
      </div>
    </div>
  )
}

const METRIC_LABELS = {
  rain_24h_mm: '24h 降雨 (mm)', rain_24h_next_mm: '次日降雨 (mm)', rain_72h_mm: '72h 累积 (mm)',
  rain_168h_mm: '168h 累积 (mm)', rain_max_h_mm: '峰值雨强 (mm/h)', sm1: '土壤湿度 0-7cm',
  wind_kt: '风速 (kt)', pres_hpa: '中心气压 (hPa)', model_prob: '模型概率',
  official_level: '官方预警', river_peak_level_m: '河道洪峰 (m)', river_peak_time: '洪峰时刻',
  warning_time: '预警时刻', hours_above_2m: '>2m 时长 (h)', contrast_rain_24h_mm: '对照日雨量 (mm)',
  contrast_model_prob: '对照模型概率', wave_peak_m: '波浪峰值 (m)', tide_peak_m: '潮位峰值 (m)',
}

function formatMetric(v, key) {
  // 概率类字段（0-1）转百分比；土壤湿度保留 3 位小数
  if (typeof v === 'number') {
    if (key === 'model_prob' || key === 'contrast_model_prob') return `${(v * 100).toFixed(1)}%`
    if (key === 'sm1') return v.toFixed(3)
    return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1)
  }
  if (typeof v === 'object') {
    return Object.entries(v).map(([k, x]) => `${k} ${x}`).join(' · ')
  }
  return String(v)
}


/* ============================== 历史事件库 ============================== */

function EventsTab() {
  const [data, setData] = useState(null)

  useEffect(() => {
    fetchJSON('/api/knowledge/events').then(setData).catch(() => setData({ error: '加载失败' }))
  }, [])

  if (!data) return <div className="card"><div className="loading">加载历史事件库…</div></div>
  if (data.error) return <div className="err-box">⚠ {data.error}</div>

  const events = data.events || []
  // 按受影响区聚合
  const districtCount = {}
  for (const e of events) {
    for (const d of e.affected || []) {
      districtCount[d] = (districtCount[d] || 0) + 1
    }
  }
  const sorted = Object.entries(districtCount).sort((a, b) => b[1] - a[1])

  return (
    <div className="kb-base">
      <div className="card kb-base-card">
        <div className="kb-block-title">🗓️ 真实历史内涝事件（公开报道口径）</div>
        <p className="kb-base-sub">共 {events.length} 个事件 · 受影响区与强度为报道量级估算</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {events.map((e) => (
            <div key={e.id} style={{ padding: '10px 12px', background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{e.date}</span>
                <b style={{ fontSize: 13 }}>{e.name}</b>
                {e.peak_intensity_mm_h && (
                  <span className="chip warn">峰值雨强 ~{e.peak_intensity_mm_h}mm/h</span>
                )}
                {e.linked_case && <span className="chip ok">已沉淀案例</span>}
              </div>
              <p style={{ margin: '6px 0 4px', fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.6 }}>{e.note}</p>
              <div style={{ fontSize: 10.5, color: 'var(--ink-4)' }}>
                受影响：{(e.affected || []).join('、') || '—'} · 来源：{e.source}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card kb-base-card">
        <div className="kb-block-title">📍 历史内涝易发区（受影响频次）</div>
        <div className="kb-rank">
          {sorted.map(([name, n]) => (
            <div key={name} className="kb-rank-row">
              <span>{name}</span>
              <div className="kb-rank-bar flood"><div style={{ width: `${(n / sorted[0][1]) * 100}%` }} /></div>
              <span className="kb-rank-v">{n} 次</span>
            </div>
          ))}
        </div>
        <p className="kb-base-sub">{data.note}</p>
      </div>
    </div>
  )
}


/* ============================== 城安助手 ============================== */

function AssistantTab() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [llm, setLlm] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    fetchJSON('/api/knowledge/suggestions')
      .then((r) => setSuggestions(r.questions || []))
      .catch(() => {})
    fetchJSON('/api/knowledge/status')
      .then(setLlm)
      .catch(() => setLlm(null))
  }, [])

  // 深链：从简报卡跳转过来的预填问题（?q= 或 sessionStorage）
  useEffect(() => {
    const q = sessionStorage.getItem('kb-prefill')
    if (q) {
      sessionStorage.removeItem('kb-prefill')
      setInput(q)
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function ask(question) {
    const q = (question || input).trim()
    if (!q || busy) return
    setBusy(true)
    setInput('')
    setMessages((m) => [...m, { role: 'user', text: q }])
    try {
      const r = await fetch('/api/knowledge/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: q,
          history: messages.slice(-6).map((m) => ({
            role: m.role === 'user' ? 'user' : 'assistant',
            content: m.role === 'user' ? m.text : (m.data?.answer || '').slice(0, 500),
          })).filter((h) => h.content),
        }),
      })
      const d = await r.json()
      setMessages((m) => [...m, { role: 'assistant', data: d }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'error', text: e.message }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="kb-assistant">
      {/* 智能服务状态条 */}
      <div className="kb-llm-status">
        {llm === null ? (
          <span className="kb-llm-chip wait">⏳ 正在检查智能服务配置</span>
        ) : llm.configured ? (
          <span className="kb-llm-chip ok">
            ● 智能服务已连接 · {llm.model}
            <em>
              {llm.retrieval?.semantic
                ? `RAG 三段式：${llm.retrieval.embed_model} 召回 → ${llm.retrieval.rerank_model} 精排 → 生成`
                : '检索增强（RAG）：本地 6 案例库 + 大模型生成'}
            </em>
          </span>
        ) : (
          <span className="kb-llm-chip warn">● 智能服务未配置，使用本地规则回答<em>配置 .env 中 LLM_* 后可启用大模型</em></span>
        )}
      </div>

      <div className="kb-chat">
        {messages.length === 0 && (
          <div className="kb-welcome">
            <div className="kb-welcome-card">
              <span className="kb-welcome-badge">🤖 案例可查</span>
              <h4>城安助手 · 案例知识库问答</h4>
              <p>基于 6 个真实事件案例与城市底座统计的检索增强问答（RAG）。</p>
              <p className="kb-hint">可以问：案例说清了什么？模型与官方预警差在哪？还缺哪些信息？</p>
            </div>
            <div className="kb-suggest-grid">
              {suggestions.map((s) => (
                <button key={s} className="kb-suggest" onClick={() => ask(s)}>{s} →</button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => {
          if (m.role === 'user') {
            return (
              <div key={i} className="kb-msg user">
                <div className="kb-msg-bubble">{m.text}</div>
                <span className="kb-avatar u">🧑</span>
              </div>
            )
          }
          if (m.role === 'error') {
            return (
              <div key={i} className="kb-msg err">
                <span className="kb-avatar a">🤖</span>
                <div className="kb-msg-bubble err">⚠ {m.text}（后端未启动？）</div>
              </div>
            )
          }
          return <AssistantAnswer key={i} data={m.data} />
        })}

        {busy && (
          <div className="kb-msg">
            <span className="kb-avatar a">🤖</span>
            <div className="kb-msg-bubble thinking">
              <ThinkingIndicator hasLlm={llm?.configured} />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="kb-input-row">
        <input
          className="kb-input" placeholder="输入知识问题（如：山竹的预警升级链是怎样的？）"
          value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ask()}
          disabled={busy}
        />
        <button className="kb-send" onClick={() => ask()} disabled={busy || !input.trim()}>
          {busy ? '…' : '发送'}
        </button>
      </div>
      <div className="kb-input-foot">
        回答由大模型基于本地案例条目生成（检索增强）· 引用与待确认项来自结构化字段 · 模型概率为历史回放非实时预报
      </div>
    </div>
  )
}


function AssistantAnswer({ data }) {
  const paragraphs = (data.answer || '').split('\n\n').filter(Boolean)
  return (
    <div className="kb-msg">
      <span className="kb-avatar a">🤖</span>
      <div className="kb-answer">
        {data.mode === 'llm' && (
          <div className="kb-mode-tag">
            ✨ {data.model || 'LLM'} 生成 · 检索增强{data.retrieval?.label ? ` · ${data.retrieval.label}` : ''}
          </div>
        )}
        {data.mode === 'local' && (
          <div className="kb-mode-tag local">
            📖 本地规则回答{data.mode_note ? ` · ${data.mode_note}` : ''}
          </div>
        )}
        {paragraphs.map((p, i) => {
          // 固定小节标题【xxx】
          const m = p.match(/^【(.+?)】\s*([\s\S]*)$/)
          if (m) {
            const items = m[2].split('\n').filter(Boolean)
            return (
              <div key={i} className={`kb-ans-sec ${secClass(m[1])}`}>
                <b>{m[1]}</b>
                {items.length === 1 ? (
                  <p>{items[0]}</p>
                ) : (
                  <ul>
                    {items.map((it, j) => <li key={j}>{it.replace(/^[·•\-\s]+/, '')}</li>)}
                  </ul>
                )}
              </div>
            )
          }
          // 普通段落（含「·」列点行则渲染为列表）
          const lines = p.split('\n').filter(Boolean)
          if (lines.length > 1 && lines.every((l) => /^[·•]/.test(l.trim()))) {
            return (
              <ul key={i} className="kb-ans-list">
                {lines.map((l, j) => <li key={j}>{l.trim().replace(/^[·•]\s*/, '')}</li>)}
              </ul>
            )
          }
          return <p key={i} className="kb-ans-p">{p}</p>
        })}

        {/* 回答依据 */}
        {data.citations?.length > 0 && (
          <div className="kb-ans-block">
            <div className="kb-block-title">📎 回答依据</div>
            {data.citations.map((c) => (
              <div key={c.case_id} className={`kb-cite ${c.case_id === 'live-snapshot' || c.case_id === 'city-base' ? 'live' : ''}`}>
                <div className="kb-cite-head">
                  <span className="kb-cite-title">
                    {c.case_id === 'live-snapshot' ? '📡 ' : c.case_id === 'city-base' ? '🏙️ ' : ''}{c.title}
                  </span>
                  <span className="kb-cite-score">
                    {c.case_id === 'live-snapshot' ? c.occurred_at : `相关度 ${c.score}`}
                  </span>
                </div>
                <p className="kb-cite-facts">{c.facts}</p>
                <p className="kb-cite-src">来源：{c.sources?.join('、')}</p>
              </div>
            ))}
          </div>
        )}

        {/* 还需确认 */}
        {data.needs_confirm?.length > 0 && (
          <div className="kb-ans-block">
            <div className="kb-block-title">🔍 还需确认（结构化字段）</div>
            {data.needs_confirm.map((n, i) => (
              <div key={i} className="kb-confirm-item">
                <span>⏳ {n.item}</span>
                <em className="kb-confirm-case">{n.case}</em>
              </div>
            ))}
          </div>
        )}

        {/* 建议动作 */}
        {data.actions?.length > 0 && (
          <div className="kb-ans-block">
            <div className="kb-block-title">🎯 建议动作</div>
            {data.actions.map((a, i) => (
              <div key={i} className="kb-action">
                <b>{a.label}</b>
                <span>{a.detail}</span>
                {a.requires_approval && <em className="kb-approve">需人工批准</em>}
              </div>
            ))}
          </div>
        )}

        <div className="kb-ans-foot">
          {data.generated_at && <span>{data.generated_at}</span>}
          <span>匹配 {data.scope?.matched ?? 0}/{data.scope?.cases_total ?? 6} 案例 · 生产知识 {data.scope?.production_knowledge ?? 0} 条</span>
        </div>
      </div>
    </div>
  )
}

function secClass(label) {
  if (label.includes('已知')) return 'ok'
  if (label.includes('未知') || label.includes('确认')) return 'warn'
  if (label.includes('复盘') || label.includes('模型')) return 'info'
  if (label.includes('经验')) return 'lesson'
  if (label.includes('关联')) return 'info'
  return ''
}


/* ============================== 城市底座 ============================== */

function CityBaseTab() {
  const [base, setBase] = useState(null)

  useEffect(() => {
    fetchJSON('/api/knowledge/city-base').then(setBase).catch(() => setBase({ error: '加载失败' }))
  }, [])

  if (!base) return <div className="card"><div className="loading">加载城市底座统计…</div></div>
  if (base.error) return <div className="card"><div className="err-box">⚠ {base.error}</div></div>

  const pop = base.population || {}
  const bld = base.buildings || {}
  const ter = base.terrain || {}
  const expo = base.exposure || {}

  return (
    <div className="kb-base">
      <div className="kb-base-grid">
        {/* 人口 */}
        <div className="card kb-base-card">
          <div className="kb-block-title">👥 人口（WorldPop 栅格）</div>
          <div className="kb-big-num">{(pop.total_1km / 1e4).toFixed(0)}<span className="kb-unit">万</span></div>
          <p className="kb-base-sub">1km 栅格合计 · 100m 口径 {((pop.total_100m || 0) / 1e4).toFixed(0)} 万</p>
          <div className="kb-rank">
            {Object.entries(pop.by_district_1km || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <div key={k} className="kb-rank-row">
                <span>{k}</span>
                <div className="kb-rank-bar"><div style={{ width: `${(v / 3064014) * 100}%` }} /></div>
                <span className="kb-rank-v">{(v / 1e4).toFixed(0)}万</span>
              </div>
            ))}
          </div>
        </div>

        {/* 建筑 */}
        <div className="card kb-base-card">
          <div className="kb-block-title">🏗️ 建筑（OSM）</div>
          <div className="kb-big-num">{(bld.total || 0).toLocaleString()}<span className="kb-unit">栋</span></div>
          <p className="kb-base-sub">100m+ 超高层 {(bld.above_100m || 0).toLocaleString()} 栋 · 平均高 {bld.mean_height_m}m</p>
          <div className="kb-rank">
            {Object.entries(bld.by_district_top || {}).map(([k, [n, hi]]) => (
              <div key={k} className="kb-rank-row">
                <span>{k}</span>
                <div className="kb-rank-bar"><div style={{ width: `${(n / 12033) * 100}%` }} /></div>
                <span className="kb-rank-v">{n.toLocaleString()} / <b className="kb-hi">{hi}</b></span>
              </div>
            ))}
          </div>
          <p className="kb-base-sub"><span className="kb-hi">红色</span> = 100m+ 超高层栋数（南山 573 全市第一）</p>
        </div>

        {/* 地形 */}
        <div className="card kb-base-card">
          <div className="kb-block-title">⛰️ 地形（Copernicus DEM 30m）</div>
          <div className="kb-ter-grid">
            <div className="kb-ter"><b>{ter.dem_min_m}</b><span>最低 (m)</span></div>
            <div className="kb-ter"><b>{ter.dem_max_m}</b><span>最高 (m)</span></div>
            <div className="kb-ter"><b>{ter.below_5m_pct}%</b><span>&lt;5m 低洼</span></div>
            <div className="kb-ter"><b>{ter.slope_above_25deg_pct}%</b><span>坡度&gt;25°</span></div>
          </div>
          <p className="kb-base-sub">27.7% 国土低于 5m（沿海内涝敏感）；7.6% 坡度超 25°（滑坡敏感带）。</p>
        </div>

        {/* 暴露 */}
        <div className="card kb-base-card">
          <div className="kb-block-title">🎯 隐患点人口暴露（600m 缓冲）</div>
          <div className="kb-expo-rows">
            <div className="kb-expo-row">
              <span className="kb-expo-k">🌧️ {expo.flood_2019_points} 易涝点周边</span>
              <b>{((expo.pop_near_flood_600m || 0) / 1e4).toFixed(0)} 万人</b>
            </div>
            <div className="kb-expo-row">
              <span className="kb-expo-k">⛰️ {expo.landslide_points} 滑坡点周边</span>
              <b>{((expo.pop_near_landslide_600m || 0) / 1e4).toFixed(0)} 万人</b>
            </div>
          </div>
          <div className="kb-rank">
            {Object.entries(expo.flood_expo_top || {}).map(([k, v]) => (
              <div key={k} className="kb-rank-row">
                <span>{k}</span>
                <div className="kb-rank-bar"><div style={{ width: `${(v / 989306) * 100}%` }} /></div>
                <span className="kb-rank-v">{(v / 1e4).toFixed(0)}万</span>
              </div>
            ))}
          </div>
          <p className="kb-base-sub">易涝暴露前三：福田 99 万、龙岗 99 万、罗湖 64 万。</p>
        </div>
      </div>

      {/* 分区内涝风险画像 */}
      <FloodProfilePanel />

      {/* 隐患点分布 */}
      <div className="card kb-base-card">
        <div className="kb-block-title">📍 隐患点分区分布（官方在册）</div>
        <div className="kb-points-grid">
          <div>
            <p className="kb-points-h">滑坡隐患点（300 个，规自局 2023 更新）</p>
            {Object.entries(base.landslide_points_by_district || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <div key={k} className="kb-rank-row">
                <span>{k}</span>
                <div className="kb-rank-bar slide"><div style={{ width: `${(v / 56) * 100}%` }} /></div>
                <span className="kb-rank-v">{v}</span>
              </div>
            ))}
          </div>
          <div>
            <p className="kb-points-h">2019 官方易涝点（206 个，天地图地理编码）</p>
            {Object.entries(base.flood_points_2019_by_district || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <div key={k} className="kb-rank-row">
                <span>{k}</span>
                <div className="kb-rank-bar flood"><div style={{ width: `${(v / 57) * 100}%` }} /></div>
                <span className="kb-rank-v">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="kb-disclaimer">统计为研究口径：人口来自 WorldPop 栅格估计、建筑高度为 OSM 估计、暴露为 600m 圆形缓冲简化。</p>
    </div>
  )
}


/* ============================== 模型档案 ============================== */

function ModelsTab() {
  const [models, setModels] = useState(null)

  useEffect(() => {
    fetchJSON('/api/knowledge/models').then(setModels).catch(() => setModels({ error: '加载失败' }))
  }, [])

  if (!models) return <div className="card"><div className="loading">加载模型档案…</div></div>
  if (models.error) return <div className="card"><div className="err-box">⚠ {models.error}</div></div>

  return (
    <div className="kb-models">
      {(models.models || []).map((m) => (
        <div key={m.id} className="card kb-model-card">
          <div className="kb-model-head">
            <b>{m.name}</b>
            <span className="kb-model-task">{m.task}</span>
          </div>
          <div className="kb-model-grid">
            <div className="kb-model-kv"><span>标签</span><b>{m.labels}</b></div>
            <div className="kb-model-kv"><span>验证</span><b>{m.validation}</b></div>
            <div className="kb-model-kv"><span>主指标</span><b className="kb-model-metric">
              {m.test_auc ? `AUC ${m.test_auc}` : m.spatial_cv_auc ? `CV AUC ${m.spatial_cv_auc}` : `拟合 R² ${m.fit_r2}`}
            </b></div>
            <div className="kb-model-kv"><span>特征</span><b>{(m.top_features || []).join(' · ')}</b></div>
          </div>
          <div className="kb-model-limit">
            <b>⚠️ 诚实局限</b>
            <p>{m.limitation}</p>
          </div>
        </div>
      ))}
      <p className="kb-disclaimer">指标全部来自真实标签训练与防泄漏验证（空间分块 / 留一事件 / 时间外）；详见 docs/TRAINING_REPORT.md。</p>
    </div>
  )
}


function ThinkingIndicator({ hasLlm }) {
  const [stage, setStage] = useState(0)
  const stages = hasLlm
    ? ['正在检索案例库…', '语义召回 + 重排序…', '注入实时数据…', '大模型生成回答…（约 10-60 秒）']
    : ['正在检索案例库…', '本地规则生成回答…']
  useEffect(() => {
    const t = setInterval(() => setStage(s => Math.min(s + 1, stages.length - 1)), 4000)
    return () => clearInterval(t)
  }, [])
  return (
    <span>
      <span className="dots">
        <i>.</i><i>.</i><i>.</i>
      </span> {stages[stage]}
    </span>
  )
}
