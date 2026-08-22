import { fmtTime, levelColor, LEVEL_LABELS, provColor, provLabel } from '../api'

export default function DistrictPanel({ view, hour, hours }) {
  const sorted = [...view].sort((a, b) => b.at.prob - a.at.prob)
  return (
    <div className="card panel-card">
      <div className="card-h">分区分时风险排行（{fmtTime(hours[hour])}）</div>
      <div className="rows">
        {sorted.map((d, i) => (
          <div className="row" key={d.id}>
            <span className="rank">{i + 1}</span>
            <span className="dname">{d.name}</span>
            <span
              className="badge"
              style={{ background: levelColor(d.at.level) }}
            >
              {LEVEL_LABELS[d.at.level]} {(d.at.prob * 100).toFixed(0)}%
            </span>
            {d.at.surrogate && (
              <span
                className="badge sub"
                title={`物理代理（§3.3）· ${provLabel(d.at.surrogate.provenance)}`}
                style={{ background: provColor(d.at.surrogate.provenance) }}
              >
                物理代理 {(d.at.surrogate.prob * 100).toFixed(0)}%
              </span>
            )}
            <span className="driver">{d.at.driver}</span>
            <span className="peak">
              峰值 {fmtTime(d.peak.time)} · {d.peak.level_label}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
