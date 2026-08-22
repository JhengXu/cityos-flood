import { useState } from 'react'

const PRESETS = [
  { key: 'typhoon_tide', label: '台风 + 天文大潮' },
  { key: 'pump_failure', label: '泵站降效 65%' },
  { key: 'extreme', label: '极端特大暴雨' },
  { key: 'baseline', label: '现状预报（基线）' },
]

export default function ScenarioPanel({ onRun, loading }) {
  const [custom, setCustom] = useState({
    rainfall_multiplier: 1.3,
    add_peak_mm: 22,
    drainage_factor: 0.85,
    tide_raise: 0.35,
  })
  const set = (k, v) => setCustom((c) => ({ ...c, [k]: v }))

  return (
    <div className="card scenario">
      <div className="card-h">
        What-if 情景沙盘
        <span className="hint">叠加到真实降雨预报上，用 LSTM 重算全城风险</span>
      </div>

      <div className="preset-row">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            className="preset-btn"
            disabled={loading}
            onClick={() => onRun({ preset: p.key })}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="custom">
        <div className="cust-title">自定义情景参数</div>
        {[
          ['rainfall_multiplier', '降雨放大 ×', 0.5, 3, 0.1, (v) => `×${v}`],
          ['add_peak_mm', '额外暴雨峰值 (mm/h)', 0, 100, 1, (v) => v],
          ['drainage_factor', '泵站/排水效能', 0.5, 1, 0.05, (v) => `${Math.round(v * 100)}%`],
          ['tide_raise', '潮位抬升', 0, 0.6, 0.05, (v) => v.toFixed(2)],
        ].map(([k, label, min, max, step, fmt]) => (
          <label key={k} className="slider">
            <span>{label}</span>
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={custom[k]}
              onChange={(e) => set(k, +e.target.value)}
            />
            <b>{fmt(custom[k])}</b>
          </label>
        ))}
        <button className="run-btn" disabled={loading} onClick={() => onRun({ ...custom })}>
          ▶ 运行推演
        </button>
      </div>
    </div>
  )
}
