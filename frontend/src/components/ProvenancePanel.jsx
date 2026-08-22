import { provColor, provLabel } from '../api'

// 数据可信度面板：把每个信号的来源按 理论 §16 标注 observed/estimated/assumed/simulated
export default function ProvenancePanel({ data }) {
  const prov = data?.provenance
  const hm = data?.hazard_model
  if (!prov && !hm) return null
  const entries = prov ? Object.entries(prov).filter(([k]) => k !== 'note') : []
  const order = ['observed', 'estimated', 'assumed', 'simulated']
  return (
    <div className="card panel-card">
      <div className="card-h">
        数据可信度 · 来源标注
        <span className="hint">理论 §16：observed / estimated / assumed / simulated</span>
      </div>
      <div className="prov-legend">
        {order.map((t) => (
          <span className="prov-chip" key={t} style={{ borderColor: provColor(t), color: provColor(t) }}>
            {provLabel(t)}
          </span>
        ))}
      </div>
      <div className="prov-rows">
        {entries.map(([k, v]) => {
          const tag = String(v).split(/[ (]/)[0].toLowerCase()
          const detail = typeof v === 'string' && v.includes('(') ? v.slice(v.indexOf('(')) : ''
          return (
            <div className="prov-row" key={k}>
              <span className="prov-k">{k}</span>
              <span className="prov-v" style={{ color: provColor(v), borderColor: provColor(v) }}>{provLabel(v)}</span>
              <span className="prov-d">{detail}</span>
            </div>
          )
        })}
      </div>
      {hm && (
        <div className="prov-note">
          <b>{hm.name}</b>：{hm.note}
        </div>
      )}
      {prov?.note && <div className="prov-note">{prov.note}</div>}
    </div>
  )
}
