import { useEffect, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Area, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts'
import { getCurrent, uploadData, manualForecast } from '../api'

const DISTRICTS = ['futian', 'luohu', 'nanshan', 'baoan', 'longgang', 'yantian', 'longhua', 'pingshan', 'guangming', 'dapeng']
const NAMES = { futian: '福田', luohu: '罗湖', nanshan: '南山', baoan: '宝安', longgang: '龙岗', yantian: '盐田', longhua: '龙华', pingshan: '坪山', guangming: '光明', dapeng: '大鹏' }

export default function DataLabPanel({ onDataUpdated }) {
  const [current, setCurrent] = useState(null)
  const [now, setNow] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [upMsg, setUpMsg] = useState(null)
  const [drag, setDrag] = useState(false)
  const [sel, setSel] = useState('baoan')
  const [rain, setRain] = useState([0, 5, 18, 40, 22, 10, 4, 2])
  const [tide, setTide] = useState(0.2)
  const [fore, setFore] = useState(null)

  async function loadNow() {
    try {
      const d = await getCurrent()
      setCurrent(d)
      const items = DISTRICTS.filter((k) => k in d.districts).map((k) => ({
        name: NAMES[k], rain: d.districts[k],
      })).sort((a, b) => b.rain - a.rain)
      setNow(items)
    } catch (e) { /* 忽略 */ }
  }

  useEffect(() => { loadNow() }, [])

  async function onFile(f) {
    if (!f) return
    setUploading(true); setUpMsg(null)
    try {
      const res = await uploadData(f)
      if (res.status === 'ok') {
        setUpMsg(`已上传 "${res.saved}"（${res.rows} 行），重训完成。命中率 ${(res.report.metrics.hit_rate * 100).toFixed(1)}%，AUC ${res.report.auc}`)
        if (onDataUpdated) onDataUpdated()
      } else {
        setUpMsg(`上传失败：${res.hint || '未知'}`)
      }
    } catch (e) {
      setUpMsg(`上传异常：${e.message}`)
    } finally {
      setUploading(false)
    }
  }

  async function runFore() {
    const r = await manualForecast({ district_id: sel, rainfall: rain.map(Number), tide_raise: tide })
    setFore(r)
  }

  const fc = fore ? fore.trajectory.map((t, i) => ({
    h: t.h, prob: t.prob * 100,
    ci: [t.lo * 100, t.hi * 100],
  })) : null

  return (
    <section className="card stage">
      <div className="card-h">
        数据实验室 · 最新数据 + 用户输入
        <span className="hint">实时最新降雨 / 上传真实数据重训 / 手动输入预测</span>
      </div>

      {/* 实时最新数据 */}
      <div className="datalab-grid">
        <div className="dl-cell">
          <div className="dl-h">
            ● 实时最新降雨（Open-Meteo）
            <button className="mini" onClick={loadNow}>↻ 刷新</button>
          </div>
          <div className="dl-src">{current ? `数据源：${current.data_source} · ${current.hour || ''}` : '加载中…'}</div>
          <div className="now-list">
            {(now || []).map((n) => (
              <div className="now-row" key={n.name}>
                <span className="now-name">{n.name}</span>
                <span className="now-bar"><i style={{ width: `${Math.min(100, n.rain * 4)}%` }} /></span>
                <span className="now-val">{n.rain.toFixed(1)}mm/h</span>
              </div>
            ))}
          </div>
        </div>

        {/* 上传真实数据 */}
        <div className="dl-cell">
          <div className="dl-h">上传真实数据 → 监督重训</div>
          <div className={`drop ${drag ? 'on' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files[0]) }}>
            <div className="drop-ic">⇪</div>
            <div className="drop-t">拖拽 CSV 到此处，或</div>
            <label className="mini">选择文件<input type="file" accept=".csv" hidden onChange={(e) => onFile(e.target.files[0])} /></label>
          </div>
          <div className="drop-hint">列：timestamp,district_id,rainfall_mm,flooded(0/1)（见 docs/model_data_contract.md）</div>
          {uploading && <div className="empty">重训中…（约 30 秒）</div>}
          {upMsg && <div className="push-ok">{upMsg}</div>}
        </div>

        {/* 手动输入预测 */}
        <div className="dl-cell">
          <div className="dl-h">手动输入 → 模型预测</div>
          <div className="form-row">
            <label>区县</label>
            <select value={sel} onChange={(e) => setSel(e.target.value)}>
              {DISTRICTS.map((k) => <option key={k} value={k}>{NAMES[k]}</option>)}
            </select>
            <label>潮位 +</label>
            <input type="number" value={tide} step="0.05" onChange={(e) => setTide(+e.target.value)} />
          </div>
          <div className="form-row rain">
            <label>逐时降雨(mm/h，逗号)</label>
            <input value={rain.join(',')} onChange={(e) => setRain(e.target.value.split(',').map(Number))} />
          </div>
          <button className="run-btn" onClick={runFore}>▶ 运行预测</button>
          {fore && (
            <div className="fore-res">
              <div className="fore-peak">峰值 {fore.peak_prob.toFixed(2)} · 等级 <b style={{ color: '#e08a1e' }}>{fore.peak_level}</b></div>
              <ResponsiveContainer width="100%" height={140}>
                <LineChart data={fc} margin={{ top: 5, right: 8, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="rgba(255,255,255,.06)" />
                  <XAxis dataKey="h" tick={{ fill: '#8C9098', fontSize: 9 }} interval={Math.floor(fc.length / 8)} />
                  <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={[0, 100]} unit="%" />
                  <Tooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area dataKey="ci" stroke="none" fill="rgba(20,91,255,.18)" name="95%置信" />
                  <Line type="monotone" dataKey="prob" stroke="#145BFF" strokeWidth={2} dot={false} name="预测" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
