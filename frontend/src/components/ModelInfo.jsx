import { levelColor, LEVEL_LABELS } from '../api'

export default function ModelInfo({ data }) {
  const m = data.model || {}
  const weights = m.hybrid_weights || {}
  const fi = m.hybrid_feature_importance || {}
  const labels = m.hybrid_feature_labels || {}
  return (
    <section className="model card">
      <div className="card-h">
        城市内涝「世界行为模型」
        <span className="hint">{m.name}</span>
      </div>
      <div className="model-body">
        <div className="model-col">
          <div className="mc-h">特征权重（sigmoid 线性项）</div>
          {Object.entries(weights).map(([k, v]) => (
            <div className="mc-row" key={k}>
              <span>{labels[k] || k}</span>
              <span className="num">{v}</span>
            </div>
          ))}
          <div className="mc-row bias">
            <span>偏置 bias</span>
            <span className="num">{m.hybrid_bias}</span>
          </div>
          {m.lstm && (
            <div className="mc-row">
              <span>LSTM 时序推演</span>
              <span className="num">
                {m.lstm.input_dim}维 → {m.lstm.hidden}隐
              </span>
            </div>
          )}
        </div>
        <div className="model-col">
          <div className="mc-h">特征重要性（归一化）</div>
          {Object.entries(fi).map(([k, v]) => (
            <div className="bar-row" key={k}>
              <span className="bar-label">{labels[k] || k}</span>
              <span className="bar-track">
                <span className="bar-fill" style={{ width: `${v * 100}%` }} />
              </span>
              <span className="num">{(v * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
        <div className="model-col">
          <div className="mc-h">风险分级</div>
          <div className="levels">
            {LEVEL_LABELS.map((l, i) => (
              <span key={l} className="lv" style={{ background: levelColor(i) }}>
                {l}
              </span>
            ))}
          </div>
          <div className="mc-note">{m.notes}</div>
        </div>
      </div>
    </section>
  )
}
