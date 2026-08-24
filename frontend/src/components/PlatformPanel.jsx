import { useEffect, useState } from 'react'
import { getPlatformRealtime, getPlatformGeocode } from '../api'

export default function PlatformPanel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const [geoQ, setGeoQ] = useState('深圳市宝安区政府')
  const [geoRes, setGeoRes] = useState(null)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const d = await getPlatformRealtime()
      setData(d)
    } catch (e) { setErr(e.message || '加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  async function runGeo() {
    const r = await getPlatformGeocode(geoQ).catch(() => null)
    setGeoRes(r)
  }

  const od = data?.opendata
  const stations = od?.top_stations || []

  return (
    <section className="card stage">
      <div className="card-h">
        平台水位快照 · 时效审计
        <span className="hint">深圳开放平台积水点水位 / 观测时刻与缓存状态 / 天地图地理编码</span>
        <button className="mini" onClick={load} disabled={loading}>{loading ? '抓取中…' : '↻ 刷新'}</button>
      </div>

      {/* 数据源状态 */}
      <div className="pf-srcrow">
        <span className="pf-src"><i className="dot ok" />开放平台水位 {data ? (od.ok ? `${od.count} 站` : '⚠') : '…'}</span>
        <span className="pf-src"><i className="dot ok" />天地图地理编码</span>
        <span className="pf-src"><i className="dot ok" />CHIRPS/OSM/高程 免费源</span>
      </div>
      {data?.timestamp && <div className="pf-ts">请求时间：{data.timestamp.replace('T', ' ').slice(0, 19)} · 观测最新时刻：{od?.observed_at?.replace('T', ' ').slice(0, 19) || '未知'} · 时效：{od?.freshness || '未知'}{od?.age_hours != null ? ` (${od.age_hours}h)` : ''} · 数据源：{od?.source}</div>}

      {od && (
        <div className="pf-kpis">
          <div className="pf-kpi"><span>积水点站</span><b>{od.count}</b></div>
          <div className="pf-kpi"><span>≥{od.threshold_m}m 积涝预警</span><b style={{ color: od.flooding_count > 0 ? '#d6452a' : '#1f7a4d' }}>{od.flooding_count}</b></div>
        </div>
      )}

      {/* 实时积水点水位趋势（前若干站） */}
      <div className="pf-table">
        <div className="pf-head"><span>站名</span><span>水位(m)</span><span>时间</span><span>状态</span><span>坐标</span></div>
        {stations.slice(0, 12).map((s, i) => (
          <div className="pf-row" key={i}>
            <span className="pf-name">{s.name.slice(0, 18)}</span>
            <span className={s.flooding ? 'pf-lvl hot' : 'pf-lvl'}>{s.level}</span>
            <span className="pf-t">{s.time ? s.time.slice(11, 19) : '—'}</span>
            <span className={s.flooding ? 'hot' : 'ok'}>{s.flooding ? '积涝' : '正常'}</span>
            <span className="pf-c">{s.lat != null ? `${(+s.lat).toFixed(3)},${(+s.lon).toFixed(3)}` : '—'}</span>
          </div>
        ))}
      </div>
      {stations.length === 0 && data && <div className="empty">当前无水位数据（历史事件期或缺免账号数据）</div>}

      {/* 天地图地理编码 */}
      <div className="pf-geo">
        <input value={geoQ} onChange={(e) => setGeoQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && runGeo()} />
        <button className="mini" onClick={runGeo}>百度式地理编码</button>
      </div>
      {geoRes && (
        <div className="pf-geo-res">
          {geoRes.location
            ? <>📍 {geoRes.query} → ({geoRes.location[0].toFixed(5)}, {geoRes.location[1].toFixed(5)})</>
            : <>未命中：{geoRes.query}</>}
        </div>
      )}
      {data?.errors?.opendata && <div className="push-ok">{data.errors.opendata}</div>}
      {err && <div className="empty">⚠ {err}</div>}
      <div className="mc-note">如需实时刷新，请在本地 .env 配置开放平台会话；未配置或会话过期时，界面只显示带观测时刻的历史缓存，不会冒充实时数据。</div>
    </section>
  )
}
