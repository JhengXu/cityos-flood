import { useEffect, useState } from 'react'
import { getRoles } from '../api'

const ROLE_ICON = { spatiotemporal: '◈', uncertainty: '∿', intervention: '◎' }

export default function RolesPanel() {
  const [roles, setRoles] = useState(null)
  useEffect(() => {
    getRoles().then((d) => setRoles(d.roles)).catch(() => setRoles([]))
  }, [])
  if (!roles) return null
  return (
    <section className="card stage">
      <div className="card-h">
        AI 三重角色 · 从"预测"到"决策"
        <span className="hint">时序/空间学习 → 不确定性量化 → 干预择优</span>
      </div>
      <div className="roles-grid">
        {roles.map((r) => (
          <div className="role" key={r.id}>
            <div className="role-ic">{ROLE_ICON[r.id]}</div>
            <div className="role-h">{r.title}</div>
            <div className="role-sub">{r.subtitle}</div>
            <div className="role-desc">{r.desc}</div>
            <div className="role-model">方法：{r.model}</div>
            <div className="role-out">
              {r.output.map((o, i) => <span key={i} className="tag">{o}</span>)}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
