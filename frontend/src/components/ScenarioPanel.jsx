import { useState } from 'react'

const PRESETS = [
  { key: 'rain_6h_before_tide', label: '雨峰提前6h' },
  { key: 'rain_with_tide', label: '雨潮同峰' },
  { key: 'rain_6h_after_tide', label: '雨峰滞后6h' },
  { key: 'typhoon_tide', label: '台风 + 天文大潮 + 排水降效15%' },
  { key: 'pump_failure', label: '泵站失效 65%（剩余 35%）' },
  { key: 'extreme', label: '极端特大暴雨（仅降雨）' },
  { key: 'baseline', label: '现状预报（基线）' },
]

export default function ScenarioPanel({ onRun, loading }) {
  const [custom, setCustom] = useState({
    rainfall_multiplier: 1.3,
    add_peak_mm: 22,
    drainage_factor: 0.85,
    pump_efficiency: 0.9,
    tide_amplitude_m: 0.85,
    surge_peak_m: 0.5,
    surge_peak_offset_h: 20,
    surge_duration_h: 12,
    rain_tide_peak_offset_h: 0,
  })
  const set = (k, v) => setCustom((c) => ({ ...c, [k]: v }))

  return (
    <div className="card scenario">
      <div className="card-h">
        What-if 情景沙盘
        <span className="hint">在同一预报快照上扰动降雨/潮位/排水边界，用守恒集合模型重算水深与超阈概率</span>
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
          ['drainage_factor', '整体排水能力倍率（含泵）', 0.5, 1, 0.05, (v) => `${Math.round(v * 100)}%`],
          ['pump_efficiency', '泵站剩余效能', 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`],
          ['tide_amplitude_m', '天文潮振幅 (m)', 0.3, 1.4, 0.05, (v) => v.toFixed(2)],
          ['surge_peak_m', '风暴增水峰值 (m)', 0, 1.8, 0.05, (v) => v.toFixed(2)],
          ['surge_peak_offset_h', '增水峰值时刻 (+h)', 0, 71, 1, (v) => v],
          ['surge_duration_h', '增水过程时长 (h)', 3, 36, 1, (v) => v],
          ['rain_tide_peak_offset_h', '雨峰相对高潮 (h)', -12, 12, 1, (v) => `${v > 0 ? '+' : ''}${v}`],
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
