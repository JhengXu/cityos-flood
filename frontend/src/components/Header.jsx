import { fmtTime, levelColor, LEVEL_LABELS } from '../api'

export default function Header({ data, onRefresh, loading }) {
  const isLiveWeather = String(data?.data_source || '').startsWith('open-meteo')

  return (
    <header className="hdr">
      <div className="brand">
        <span className="logo">◼</span>
        <div>
          <div className="b1">CITY OS</div>
          <div className="b2">深圳城市内涝推演 · 守恒图状态空间集合 + 局地 EnSRF</div>
        </div>
      </div>
      <div className="hdr-right">
        {data && (
          <span className={`src ${isLiveWeather ? 'live' : 'sample'}`}>
            {isLiveWeather ? '● 最新签发天气预报' : '○ 合成降雨回退'}
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
