import { fmtTime, levelColor, LEVEL_LABELS } from '../api'

export default function Header({ data, onRefresh, loading }) {
  return (
    <header className="hdr">
      <div className="brand">
        <span className="logo">◼</span>
        <div>
          <div className="b1">CITY OS</div>
          <div className="b2">深圳城市内涝预测 · 世界行为模型驱动</div>
        </div>
      </div>
      <div className="hdr-right">
        {data && (
          <span className={`src ${data.data_source === 'open-meteo' ? 'live' : 'sample'}`}>
            {data.data_source === 'open-meteo' ? '● 实时天气' : '○ 样例数据'}
          </span>
        )}
        <button onClick={onRefresh} disabled={loading}>
          {loading ? '刷新中…' : '↻ 刷新数据'}
        </button>
      </div>
    </header>
  )
}

export { fmtTime, levelColor, LEVEL_LABELS }
