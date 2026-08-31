import { useEffect, useState, useRef } from 'react'

/**
 * AlertStream — 实时告警流（阈值触发）
 * 数据来自 /api/live 的 alerts 数组（后端 live_ops 计算）
 */
const SEV_META = {
  critical: { label: '警示', color: 'var(--danger)', icon: '🔴' },
  warning: { label: '关注', color: 'var(--warn)', icon: '🟡' },
  info: { label: '提示', color: 'var(--accent)', icon: '🔵' },
}

export default function AlertStream({ alerts = [], generatedAt = '' }) {
  const [expanded, setExpanded] = useState(true)
  const [muted, setMuted] = useState(() => localStorage.getItem('cityos-alert-muted') === '1')
  const lastCriticalRef = useRef(0)

  // 警示级告警 → 短促提示音（Web Audio 合成，无资源文件）
  useEffect(() => {
    if (muted) return
    const criticalCount = alerts.filter((a) => a.severity === 'critical').length
    if (criticalCount > lastCriticalRef.current && lastCriticalRef.current >= 0) {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)()
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.connect(gain); gain.connect(ctx.destination)
        osc.frequency.value = 880
        osc.type = 'sine'
        gain.gain.setValueAtTime(0.08, ctx.currentTime)
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4)
        osc.start(); osc.stop(ctx.currentTime + 0.4)
        osc.onended = () => ctx.close()
      } catch (e) { /* autoplay 限制时静默 */ }
    }
    lastCriticalRef.current = criticalCount
  }, [alerts, muted])

  const toggleMute = () => {
    const v = !muted
    setMuted(v)
    localStorage.setItem('cityos-alert-muted', v ? '1' : '0')
  }

  // SSE 订阅：告警变化时父组件刷新（OverviewPage 传 onAlertsChange）
  useEffect(() => {
    let es = null
    try {
      es = new EventSource('/api/alerts/stream')
      es.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data)
          if (d.type === 'alerts' && Array.isArray(d.alerts) && d.alerts.length >= 0) {
            window.dispatchEvent(new CustomEvent('cityos:alerts-updated', { detail: d.alerts }))
          }
        } catch (e) { /* ignore parse errors */ }
      }
    } catch (e) { /* SSE 不可用时静默（轮询兜底） */ }
    return () => { if (es) es.close() }
  }, [])

  const counts = { critical: 0, warning: 0, info: 0 }
  for (const a of alerts) counts[a.severity] = (counts[a.severity] || 0) + 1

  if (!alerts.length) {
    return (
      <div className="card" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="chip ok">✓ 当前无告警</span>
        <span className="footnote">四灾种均在正常阈值内 · {generatedAt.slice(11, 19) || ''}</span>
      </div>
    )
  }

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <button
        onClick={() => setExpanded(e => !e)}
        style={{ all: 'unset', cursor: 'pointer', width: '100%', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 8 }}
      >
        <b style={{ fontSize: 13 }}>🚨 实时告警流</b>
        <span className="chip danger">{counts.critical} 警示</span>
        <span className="chip warn">{counts.warning} 关注</span>
        <span className="chip">{counts.info} 提示</span>
        <span className="chip" style={{ marginLeft: 'auto' }}>{expanded ? '收起 ▲' : '展开 ▼'}</span>
        <button className="icon-btn" style={{ width: 26, height: 26, fontSize: 12 }} onClick={toggleMute}
          title={muted ? '开启告警音' : '静音告警音'}>
          {muted ? '🔇' : '🔊'}
        </button>
      </button>
      {expanded && (
        <div style={{ maxHeight: 300, overflowY: 'auto', padding: '0 14px 12px' }}>
          {alerts.map((a, i) => {
            const m = SEV_META[a.severity] || SEV_META.info
            return (
              <div
                key={a.id}
                style={{
                  display: 'flex', gap: 10, alignItems: 'flex-start',
                  padding: '8px 10px', marginBottom: 6,
                  background: `color-mix(in srgb, ${m.color} 7%, transparent)`,
                  border: `1px solid color-mix(in srgb, ${m.color} 25%, transparent)`,
                  borderRadius: 9,
                  animation: `alertIn 0.4s ${i * 0.06}s both`,
                }}
              >
                <span style={{ fontSize: 14 }}>{m.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                    <span style={{ color: m.color }}>[{m.label}]</span>
                    <span style={{ color: 'var(--ink-3)', marginLeft: 6 }}>{a.domain}</span>
                    <span style={{ marginLeft: 8 }}>{a.title}</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2 }}>{a.note}</div>
                </div>
                <span style={{ fontSize: 9.5, color: 'var(--ink-4)', flexShrink: 0, marginTop: 2 }}>{a.source}</span>
              </div>
            )
          })}
        </div>
      )}
      <style>{`@keyframes alertIn { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: none; } }`}</style>
    </div>
  )
}
