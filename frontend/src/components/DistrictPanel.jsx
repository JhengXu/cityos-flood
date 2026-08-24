import {
  fmtTime, levelColor, LEVEL_LABELS, depthQuantilesM, exceedanceProbability,
  formatDepthM, formatPercent,
} from '../api'

export default function DistrictPanel({ view, hour, hours }) {
  const ranked = view.map((district) => ({
    ...district,
    depth: depthQuantilesM(district.at),
    exceedance: exceedanceProbability(district.at, 0.15),
  }))
  const sorted = ranked.sort((a, b) =>
    (b.depth.p50 ?? -1) - (a.depth.p50 ?? -1)
      || (b.exceedance ?? -1) - (a.exceedance ?? -1))
  return (
    <div className="card panel-card">
      <div className="card-h">
        分区集合预测（{fmtTime(hours[hour])}）
        <span className="hint">中位水深优先排序 · P(水深≥15cm)</span>
      </div>
      <div className="rows">
        {sorted.map((d, i) => (
          <div className="row district-row" key={d.id}>
            <span className="rank">{i + 1}</span>
            <span className="dname">{d.name}</span>
            <span
              className="badge"
              style={{ background: levelColor(d.at.level) }}
            >
              {d.at.level_label || LEVEL_LABELS[d.at.level] || '未分级'}
            </span>
            <span className="depth-main">
              {d.depth.available ? (
                <><b>{formatDepthM(d.depth.p50)}</b><small>P10–P90 {formatDepthM(d.depth.p10)}–{formatDepthM(d.depth.p90)}</small></>
              ) : (
                <><b>旧概率口径</b><small>{formatPercent(d.at.prob)}</small></>
              )}
            </span>
            <span className="threshold-prob">P≥15cm <b>{formatPercent(d.exceedance)}</b></span>
            <span className="driver">{d.at.driver}</span>
            <span className="peak">
              峰值 {fmtTime(d.peak?.time)} · {d.peak?.depth_p50_m != null ? formatDepthM(d.peak.depth_p50_m) : d.peak?.level_label}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
