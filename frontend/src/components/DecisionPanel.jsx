import { useEffect, useState, useCallback } from 'react'
import { fetchJSON } from '../api'

/**
 * DecisionPanel — WAM 决策工单闭环
 * 建议 → 人工批准/驳回 → 执行 → 效果回评（含审计链）
 * 数据来自 /api/decisions*
 */
const STATUS_META = {
  pending: { label: '待人工决策', color: 'var(--warn)', icon: '⏳' },
  executing: { label: '执行中', color: 'var(--accent)', icon: '⚙️' },
  done: { label: '已完成·已回评', color: 'var(--ok)', icon: '✅' },
  rejected: { label: '已驳回', color: 'var(--ink-4)', icon: '❌' },
}

export default function DecisionPanel({ onRefreshWam }) {
  const [list, setList] = useState(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [expanded, setExpanded] = useState(null)

  const load = useCallback(() => {
    fetchJSON('/api/decisions').then(setList).catch((e) => setList({ error: e.message }))
  }, [])

  useEffect(() => { load() }, [load])

  async function act(path, body) {
    setBusy(true)
    try {
      await fetch(`/api/decisions/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      load()
    } finally {
      setBusy(false)
      setNote('')
    }
  }

  if (!list) return <div className="card"><div className="loading">加载决策工单…</div></div>
  if (list.error) return <div className="err-box">⚠ {list.error}</div>

  const c = list.counts || {}
  const items = list.decisions || []

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="card-h">
        📋 WAM 决策工单闭环
        <span className="hint">建议 → 人工批准 → 执行 → 效果回评 · SHA-256 审计链</span>
      </div>

      {/* 状态统计 */}
      <div style={{ display: 'flex', gap: 8, padding: '10px 14px', flexWrap: 'wrap' }}>
        {Object.entries(STATUS_META).map(([k, m]) => (
          <span key={k} className="chip" style={{
            color: c[k] > 0 ? m.color : 'var(--ink-4)',
            borderColor: c[k] > 0 ? `color-mix(in srgb, ${m.color} 40%, transparent)` : undefined,
          }}>
            {m.icon} {m.label} {c[k] || 0}
          </span>
        ))}
      </div>

      {/* 工单列表 */}
      <div style={{ maxHeight: 520, overflowY: 'auto', padding: '0 14px 14px' }}>
        {items.length === 0 && (
          <div className="footnote" style={{ padding: 20, textAlign: 'center' }}>
            暂无决策工单。在「自主优化 WAM」页完成优化后点击「提交为决策建议」生成工单。
          </div>
        )}
        {items.map((d) => {
          const m = STATUS_META[d.status] || STATUS_META.pending
          const open = expanded === d.id
          return (
            <div key={d.id} style={{
              border: '1px solid var(--line)', borderRadius: 10,
              marginBottom: 8, overflow: 'hidden', background: 'var(--panel-2)',
            }}>
              {/* 头 */}
              <button
                onClick={() => setExpanded(open ? null : d.id)}
                style={{ all: 'unset', cursor: 'pointer', width: '100%', padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}
              >
                <span className="chip" style={{ color: m.color, borderColor: `color-mix(in srgb, ${m.color} 40%, transparent)` }}>
                  {m.icon} {m.label}
                </span>
                <span style={{ fontSize: 12, fontWeight: 600, flex: 1, textAlign: 'left' }}>{d.plan_summary}</span>
                <span className="mono" style={{ fontSize: 10, color: 'var(--ink-4)' }}>{d.id.split('-').slice(-1)[0]}</span>
                <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>{d.created_at?.slice(5, 16)}</span>
                <span style={{ color: 'var(--ink-4)' }}>{open ? '▲' : '▼'}</span>
              </button>

              {open && (
                <div style={{ borderTop: '1px solid var(--line-soft)', padding: '10px 12px' }}>
                  {/* 控制动作 */}
                  {d.control_actions?.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-2)', marginBottom: 4 }}>控制动作</div>
                      {d.control_actions.map((a, i) => (
                        <div key={i} style={{ fontSize: 11.5, color: 'var(--ink-2)', padding: '2px 0' }}>
                          · {a.district}：{a.action} {a.value} {a.expected_effect ? `（预期 ${a.expected_effect}）` : ''}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 回评（已完成） */}
                  {d.review && (
                    <div style={{ padding: '8px 10px', background: 'var(--panel-3)', borderRadius: 8, marginBottom: 8 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ok)', marginBottom: 4 }}>效果回评</div>
                      <div style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>
                        预期峰值 {d.review.expected_peak_mm}mm vs 实际 {d.review.actual_peak_mm}mm
                        （偏差 {d.review.deviation_mm > 0 ? '+' : ''}{d.review.deviation_mm}mm）
                        {d.review.note && ` · ${d.review.note}`}
                      </div>
                    </div>
                  )}

                  {/* 驳回理由 */}
                  {d.status === 'rejected' && d.reject_reason && (
                    <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginBottom: 8 }}>
                      驳回理由：{d.reject_reason}（{d.rejected_by}）
                    </div>
                  )}

                  {/* 审计时间线 */}
                  <details>
                    <summary style={{ fontSize: 11, cursor: 'pointer', color: 'var(--ink-3)' }}>审计链（{d.timeline.length} 条）</summary>
                    {d.timeline.map((t, i) => (
                      <div key={i} style={{ fontSize: 10.5, color: 'var(--ink-3)', padding: '2px 0 2px 10px', borderLeft: '2px solid var(--line)' }}>
                        {t.at} · {t.action} · {t.by} · {t.note}
                        <span className="mono" style={{ color: 'var(--ink-4)', marginLeft: 6 }}>#{t.hash}</span>
                      </div>
                    ))}
                  </details>

                  {/* 操作按钮 */}
                  {d.status === 'pending' && (
                    <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
                      <input
                        className="kb-input" style={{ flex: 1, padding: '6px 10px', fontSize: 12 }}
                        placeholder="决策备注（驳回时必填理由）" value={note}
                        onChange={(e) => setNote(e.target.value)}
                      />
                      <button className="btn sm primary" disabled={busy}
                        onClick={() => act('approve', { decision_id: d.id, note })}>
                        ✓ 批准执行
                      </button>
                      <button className="btn sm" disabled={busy || !note.trim()}
                        onClick={() => act('reject', { decision_id: d.id, note })}>
                        ✗ 驳回
                      </button>
                    </div>
                  )}
                  {d.status === 'executing' && (
                    <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
                      <input
                        className="kb-input" style={{ width: 130, padding: '6px 10px', fontSize: 12 }}
                        placeholder="实际峰值 mm" type="number"
                        onChange={(e) => setNote(e.target.value)}
                      />
                      <button className="btn sm primary" disabled={busy}
                        onClick={() => act('complete', { decision_id: d.id, flood_peak_mm_actual: parseFloat(note) || 0, note: '执行完成' })}>
                        ✓ 完成并回评
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div style={{ padding: '0 14px 12px' }}>
        <p className="footnote">{list.store} · 建议为 advisory 口径，批准后不自动下发 SCADA</p>
      </div>
    </div>
  )
}
