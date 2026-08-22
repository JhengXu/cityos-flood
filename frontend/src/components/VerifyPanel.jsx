import { useEffect, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from 'recharts'
import { getVerify, exportReport } from '../api'

export default function VerifyPanel() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    getVerify().then((d) => {
      if (d.status === 'ok') setData(d.report)
      else setErr(d.hint)
    }).catch((e) => setErr(e.message || '加载失败'))
  }, [])

  if (err) return <div className="card stage"><div className="card-h">可复现验证</div><div className="empty">{err}</div></div>
  if (!data) return null

  const cfg = data.config || {}
  const m = data.metrics
  const cal = data.calibration.fop.map((f, i) => ({ x: (f * 100).toFixed(0), y: (data.calibration.mpv[i] * 100).toFixed(0) }))
  const cards = [
    { k: 'AUC', v: data.auc, c: '#145BFF' },
    { k: 'Brier', v: data.brier, c: '#c9b458' },
    { k: '命中率 Hit', v: `${(m.hit_rate * 100).toFixed(1)}%`, c: '#1f7a4d' },
    { k: '漏报率 Miss', v: `${(m.miss_rate * 100).toFixed(1)}%`, c: '#d6452a' },
    { k: '误报率 FA', v: `${(m.false_alarm_rate * 100).toFixed(1)}%`, c: '#e08a1e' },
    { k: '预警提前量', v: data.mean_lead_time_h != null ? `${data.mean_lead_time_h}h` : '—', c: '#145BFF' },
  ]
  const replay = (data.replay || []).slice(0, 16)

  return (
    <section className="card stage">
      <div className="card-h">
        可复现验证 · 真实数据训练 + 历史回放
        <span className="hint">{data.n_test} 测试样本 · 固定种子/切分 · 数据集版本化管理</span>
        <button className="mini" onClick={exportReport}>⇩ 导出验证报告</button>
      </div>

      <div className="verify-cards">
        {cards.map((c) => (
          <div className="ov-card" key={c.k} style={{ borderColor: c.c }}>
            <div className="ov-k">{c.k}</div>
            <div className="ov-v" style={{ color: c.c }}>{c.v}</div>
          </div>
        ))}
      </div>

      {cfg.seed != null && (
        <div className="cfg-strip">
          <span>数据集 <b>{cfg.dataset_version}</b></span>
          <span>种子 <b>{cfg.seed}</b></span>
          <span>切分 <b>{cfg.split.train}/{cfg.split.val}/{cfg.split.test}</b></span>
          <span>窗口 <b>{cfg.seq_len}h</b></span>
          <span>地平线 <b>{cfg.horizon}h</b></span>
          <span>标签 <b>{cfg.data_fallback}</b></span>
        </div>
      )}

      <div className="grid">
        <div className="card chart-card">
          <div className="card-h">概率校准曲线（Reliability）</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={cal} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="rgba(255,255,255,.06)" />
              <XAxis dataKey="x" tick={{ fill: '#8C9098', fontSize: 10 }} label={{ value: '预测概率%', position: 'insideBottom', fill: '#8C9098', fontSize: 10 }} />
              <YAxis tick={{ fill: '#8C9098', fontSize: 10 }} domain={[0, 100]} label={{ value: '真实频率%', angle: -90, fill: '#8C9098', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#0B0D10', border: '1px solid rgba(255,255,255,.12)', color: '#F3F3EF' }} />
              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke="rgba(255,255,255,.25)" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="y" name="校准" stroke="#145BFF" strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card charts">
          <div className="card-h">历史事件回放（可复核证据）</div>
          <div className="replay-table">
            <div className="rt-head">
              <span>事件</span><span>区</span><span>影响</span><span>峰值</span><span>预测</span><span>实际</span><span>提前</span>
            </div>
            {replay.map((r, i) => (
              <div className="rt-row" key={i}>
                <span className="rt-event">{r.event}</span>
                <span>{r.district}</span>
                <span className={r.affected ? 'pos' : 'neg'}>{r.affected ? '受影响' : '未影响'}</span>
                <span>{r.peak_mm_h}mm/h</span>
                <span>{r.pred_peak_prob.toFixed(2)}</span>
                <span>{r.actual_flood ? '涝' : '—'}</span>
                <span>{r.lead_h != null ? `${r.lead_h}h` : '—'}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mc-note">
        训练样本：真实历史事件（2018"山竹"/2023"9·7"…）锚定的监督序列；指标由固定随机种子 + 固定切分 + 历史回放得到。真实逐时积水台账注入后，按《docs/model_data_contract.md》契约零改动切换为真实监督训练。
      </div>
    </section>
  )
}
