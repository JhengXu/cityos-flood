import { fmtTime, levelColor, LEVEL_LABELS } from '../api'

export default function CityOverview({ data, view }) {
  const ov = data.overview
  const cards = [
    {
      k: '当前城市风险',
      v: ov.current_risk_label,
      sub: `概率 ${(ov.current_risk_prob * 100).toFixed(0)}%`,
      color: levelColor(ov.current_risk_level),
    },
    {
      k: '当前高风险区',
      v: ov.high_risk_now_count,
      sub: ov.high_risk_now.length ? ov.high_risk_now.join('、') : '暂无',
      color: ov.high_risk_now_count ? '#d6452a' : '#1f7a4d',
    },
    {
      k: '风险峰值时刻',
      v: fmtTime(ov.peak_time),
      sub: `峰值 ${LEVEL_LABELS[ov.peak_risk_level]}风险`,
      color: levelColor(ov.peak_risk_level),
    },
    {
      k: '预警条数',
      v: ov.alert_count,
      sub: ov.alert_count ? '需启动应急响应' : '暂无需预警',
      color: ov.alert_count ? '#e08a1e' : '#1f7a4d',
    },
  ]

  const top = ov.alerts[0]
  return (
    <section className="overview">
      <div className="ov-grid">
        {cards.map((c) => (
          <div className="ov-card" key={c.k} style={{ borderColor: c.color }}>
            <div className="ov-k">{c.k}</div>
            <div className="ov-v" style={{ color: c.color }}>
              {c.v}
            </div>
            <div className="ov-sub">{c.sub}</div>
          </div>
        ))}
      </div>
      {top && (
        <div className="ov-alert">
          <span className="dot" style={{ background: levelColor(top.level) }} />
          最高优先级预警：{top.message}
        </div>
      )}
    </section>
  )
}
