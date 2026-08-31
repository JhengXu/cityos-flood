import { useEffect, useState } from 'react'
import { fetchJSON } from '../api'

/**
 * DailyBriefing — 今日态势简报（LLM 生成）
 * 打开态势总览时自动展示
 */
export default function DailyBriefing() {
  const [data, setData] = useState(null)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    fetchJSON('/api/knowledge/briefing').then(setData).catch(() => setData(null))
  }, [])

  if (!data || data.error) return null

  return (
    <div className="card" style={{
      overflow: 'hidden',
      border: '1px solid color-mix(in srgb, var(--accent) 25%, transparent)',
      background: 'linear-gradient(135deg, color-mix(in srgb, var(--accent) 6%, transparent), transparent 60%)',
    }}>
      <button
        onClick={() => setCollapsed(c => !c)}
        style={{ all: 'unset', cursor: 'pointer', width: '100%', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 8 }}
      >
        <span style={{ fontSize: 15 }}>📋</span>
        <b style={{ fontSize: 13 }}>今日态势简报</b>
        {data.mode === 'llm' && <span className="chip" style={{ fontSize: 9 }}>✨ {data.model || 'AI'} 生成</span>}
        <span className="footnote" style={{ marginLeft: 'auto' }}>{data.generated_at}</span>
        <span style={{ color: 'var(--ink-4)' }}>{collapsed ? '▼' : '▲'}</span>
      </button>
      {!collapsed && (
        <div style={{ padding: '0 14px 12px' }}>
          <p style={{ margin: 0, fontSize: 13, lineHeight: 1.8, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>
            {data.briefing}
          </p>
          <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            {['告警详情是什么？', '明日滑坡概率为什么高？', '风暴潮峰值何时出现？'].map((q) => (
              <button
                key={q}
                className="btn sm"
                onClick={() => {
                  sessionStorage.setItem('kb-prefill', q)
                  ;[...document.querySelectorAll('.nav-item')].find((b) => b.textContent.includes('沉淀知识库'))?.click()
                  setTimeout(() => [...document.querySelectorAll('.kb-tab')].find((t) => t.textContent.includes('城安助手'))?.click(), 150)
                }}
              >
                💬 {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
