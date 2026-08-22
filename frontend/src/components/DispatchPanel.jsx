import { useState } from 'react'
import { postDispatch, getAlerts, levelColor } from '../api'

export default function DispatchPanel({ sim, loading }) {
  const [pushed, setPushed] = useState(null)
  const [history, setHistory] = useState([])
  const alerts = sim?.alerts || []

  async function push() {
    const res = await postDispatch({ scenario: sim.scenario })
    setPushed(res)
    const a = await getAlerts()
    setHistory(a.alerts)
  }

  return (
    <div className="card dispatch">
      <div className="card-h">
        ACT 闭环 · 泵站调度 + 预警下发
        <span className="hint">{alerts.length} 条待下发</span>
      </div>

      {alerts.length === 0 && (
        <div className="empty">当前情景无达到预警级别（高/极高）的片区。</div>
      )}

      <div className="alerts">
        {alerts.map((a, i) => (
          <div className="alert-item" key={i} style={{ borderLeftColor: levelColor(a.severity) }}>
            <div className="ai-head">
              <span className="sev" style={{ background: levelColor(a.severity) }}>
                {a.severity_label}
              </span>
              {a.district}
              <span className="ai-time">{a.time}</span>
            </div>
            <div className="ai-msg">{a.message}</div>
            <div className="ai-channels">通道：{a.channels.join(' / ')}</div>
            <ul className="ai-actions">
              {a.actions.map((ac, j) => (
                <li key={j}>{ac}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {alerts.length > 0 && (
        <button className="push-btn" disabled={loading} onClick={push}>
          📣 一键下发预警（写入日志 / 可接 Webhook）
        </button>
      )}

      {pushed && (
        <div className="push-ok">已下发 {pushed.pushed} 条预警（状态：{pushed.push.map((p) => p.status).join('、')}）</div>
      )}

      {history.length > 0 && (
        <div className="hist">
          <div className="hist-h">已下发记录（最近 5 条）</div>
          {history.slice(-5).reverse().map((h, i) => (
            <div key={i} className="hist-item">
              {h.district} · {h.severity_label} · {h.time}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
