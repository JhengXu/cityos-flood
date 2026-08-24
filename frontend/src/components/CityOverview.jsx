import {
  fmtTime, levelColor, LEVEL_LABELS, depthQuantilesM, exceedanceProbability,
  formatDepthM, formatPercent,
} from '../api'

export default function CityOverview({ data, view }) {
  const ov = data.overview || {}
  const depthRows = view.map((district) => ({
    district,
    depth: depthQuantilesM(district.at),
    exceedance: exceedanceProbability(district.at, 0.15),
  })).filter((row) => row.depth.available)
  const deepest = [...depthRows].sort((a, b) => b.depth.p50 - a.depth.p50)[0]
  const mostLikely = [...depthRows].sort((a, b) => (b.exceedance ?? -1) - (a.exceedance ?? -1))[0]
  const peakRows = data.districts.flatMap((district) => (district.series || []).map((point) => ({
    district,
    point,
    depth: depthQuantilesM(point),
  }))).filter((row) => row.depth.available)
  const cityPeak = [...peakRows].sort((a, b) => b.depth.p50 - a.depth.p50)[0]
  const hasDepth = depthRows.length > 0
  const cards = hasDepth ? [
    {
      k: '首个预报时次最大中位水深',
      v: formatDepthM(deepest.depth.p50),
      sub: `${deepest.district.name} · P10–P90 ${formatDepthM(deepest.depth.p10)}–${formatDepthM(deepest.depth.p90)}`,
      color: levelColor(deepest.district.at.level),
    },
    {
      k: '首个预报时次超 15cm 最高概率',
      v: formatPercent(mostLikely?.exceedance),
      sub: mostLikely ? mostLikely.district.name : '—',
      color: (mostLikely?.exceedance || 0) >= 0.5 ? '#d6452a' : '#1f7a4d',
    },
    {
      k: '预测最大中位水深',
      v: cityPeak ? formatDepthM(cityPeak.depth.p50) : '—',
      sub: cityPeak ? `${cityPeak.district.name} · ${fmtTime(cityPeak.point.time)}` : '暂无',
      color: cityPeak ? levelColor(cityPeak.point.level) : '#1f7a4d',
    },
    {
      k: '预警条数',
      v: ov.alert_count ?? (ov.alerts || []).length,
      sub: (ov.alert_count ?? 0) ? '需结合不确定性人工复核' : '暂无需预警',
      color: (ov.alert_count ?? 0) ? '#e08a1e' : '#1f7a4d',
    },
  ] : [
    {
      k: '首个预报时次城市风险（兼容口径）',
      v: ov.first_forecast_risk_label || ov.current_risk_label || '—',
      sub: `概率 ${formatPercent(ov.first_forecast_risk_prob ?? ov.current_risk_prob)}`,
      color: levelColor(ov.first_forecast_risk_level ?? ov.current_risk_level),
    },
    {
      k: '首个预报时次高风险区',
      v: ov.high_risk_first_forecast_count ?? ov.high_risk_now_count ?? 0,
      sub: (ov.high_risk_first_forecast || ov.high_risk_now)?.length ? (ov.high_risk_first_forecast || ov.high_risk_now).join('、') : '暂无',
      color: (ov.high_risk_first_forecast_count ?? ov.high_risk_now_count) ? '#d6452a' : '#1f7a4d',
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

  const top = ov.alerts?.[0]
  const readiness = data.data_readiness || data.observation_readiness || data.data_quality
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
      {readiness && (
        <div className={`readiness-strip ${readiness.forecast_training_ready ? 'ready' : 'limited'}`}>
          <b>{readiness.forecast_training_ready ? '观测数据已满足独立训练门槛' : '独立事件验证数据不足'}</b>
          <span>{readiness.reason || readiness.note || '当前结果应视为集合物理推演，不代表已经真实灾情标签验证。'}</span>
        </div>
      )}
    </section>
  )
}
