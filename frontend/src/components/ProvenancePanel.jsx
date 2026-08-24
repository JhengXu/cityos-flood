import { provColor, provLabel } from '../api'

// 数据可信度面板：把每个信号的来源按 理论 §16 标注 observed/estimated/assumed/simulated
export default function ProvenancePanel({ data }) {
  const prov = data?.provenance
  const hm = data?.hazard_model
  const readiness = data?.data_readiness || data?.observation_readiness || data?.data_quality
  if (!prov && !hm && !readiness) return null
  const entries = prov ? Object.entries(prov).filter(([k]) => k !== 'note') : []
  const order = ['observed', 'estimated', 'assumed', 'simulated']
  return (
    <div className="card panel-card">
      <div className="card-h">
        数据来源与可用性边界
        <span className="hint">observed / estimated / assumed / simulated 逐项可追溯</span>
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
          const structured = v && typeof v === 'object'
          const raw = structured ? (v.provenance || v.status || 'metadata') : v
          const detail = structured
            ? (v.note || v.reason || JSON.stringify(v))
            : (typeof v === 'string' && v.includes('(') ? v.slice(v.indexOf('(')) : '')
          return (
            <div className="prov-row" key={k}>
              <span className="prov-k">{k}</span>
              <span className="prov-v" style={{ color: provColor(raw), borderColor: provColor(raw) }}>{provLabel(raw)}</span>
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
      {readiness && (
        <div className="prov-note">
          <b>{readiness.forecast_training_ready ? '可进入独立训练/验证' : '尚不具备独立技能验证条件'}</b>：
          {readiness.reason || readiness.note || '请核对观测时间窗、独立事件标签与空间映射。'}
        </div>
      )}
      {prov?.note && <div className="prov-note">{prov.note}</div>}
    </div>
  )
}
