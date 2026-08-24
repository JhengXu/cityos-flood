import { useEffect, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from 'recharts'
import { getVerify, exportReport } from '../api'

export default function VerifyPanel() {
  const [payload, setPayload] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    getVerify().then(setPayload).catch((e) => setErr(e.message || '加载失败'))
  }, [])

  if (err) return <div className="card stage"><div className="card-h">可复现验证</div><div className="empty">{err}</div></div>
  if (!payload) return null

  const readiness = payload.data_readiness || payload.readiness || payload.observation_readiness || {}
  const report = payload.report || {}
  const independentlyValidated = payload.status === 'ok' && (
    payload.independently_validated === true
    || payload.validation_basis === 'independent_observed_events'
    || report.independently_validated === true
    || readiness.forecast_training_ready === true
  )

  if (!independentlyValidated) {
    const readinessCards = [
      ['质控小时记录', readiness.rows],
      ['覆盖站点', readiness.stations],
      ['观测时长', readiness.duration_hours != null ? `${readiness.duration_hours}h` : null],
      ['独立洪涝事件', readiness.independent_flood_events],
      ['水深≥15cm 记录', readiness.rows_ge_0_15m],
      ['最大水深代理', readiness.max_depth_proxy_m != null ? `${readiness.max_depth_proxy_m}m` : null],
    ]
    return (
      <section className="card stage">
        <div className="card-h">
          独立验证就绪度
          <span className="hint">只有真实、时间对齐的积水事件标签才能支撑 AUC / Brier / 提前量</span>
        </div>
        <div className="status-banner limited">
          <b>当前不足以声称模型准确率</b>
          <span>{payload.hint || readiness.reason || '现有数据缺少独立灾情事件和足够的时间覆盖。'}</span>
        </div>
        <div className="verify-cards readiness-cards">
          {readinessCards.map(([label, value]) => (
            <div className="ov-card" key={label}>
              <div className="ov-k">{label}</div>
              <div className="ov-v">{value ?? '—'}</div>
            </div>
          ))}
        </div>
        <div className="evidence-note">
          <b>本页刻意不展示旧 AUC/Brier 排名。</b>
          <span>旧报告的监督标签由物理规则/事件锚点间接构造，不是与输入独立的逐时积水真值，因此不能证明泛化准确性。后续应按事件分组做时间外切分，并与持续性/水文基线比较。</span>
        </div>
      </section>
    )
  }

  const data = report

  const cfg = payload.config || data.config || {}
  const m = data.metrics || {}
  const cal = (data.calibration?.fop || []).map((f, i) => ({ x: (f * 100).toFixed(0), y: ((data.calibration?.mpv?.[i] || 0) * 100).toFixed(0) }))
  const cards = [
    { k: 'AUC', v: data.auc, c: '#145BFF' },
    { k: 'Brier', v: data.brier, c: '#c9b458' },
    { k: '命中率 Hit', v: m.hit_rate != null ? `${(m.hit_rate * 100).toFixed(1)}%` : '—', c: '#1f7a4d' },
    { k: '漏报率 Miss', v: m.miss_rate != null ? `${(m.miss_rate * 100).toFixed(1)}%` : '—', c: '#d6452a' },
    { k: '误报率 FA', v: m.false_alarm_rate != null ? `${(m.false_alarm_rate * 100).toFixed(1)}%` : '—', c: '#e08a1e' },
    { k: '预警提前量', v: data.mean_lead_time_h != null ? `${data.mean_lead_time_h}h` : '—', c: '#145BFF' },
  ]
  const replay = (data.replay || []).slice(0, 16)

  return (
    <section className="card stage">
      <div className="card-h">
        可复现独立验证
        <span className="hint">{data.n_test} 测试样本 · 事件外切分 · 数据集版本化</span>
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
          <span>切分 <b>{cfg.split?.train ?? '—'}/{cfg.split?.val ?? '—'}/{cfg.split?.test ?? '—'}</b></span>
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
                <span>{r.pred_peak_prob != null ? r.pred_peak_prob.toFixed(2) : '—'}</span>
                <span>{r.actual_flood ? '涝' : '—'}</span>
                <span>{r.lead_h != null ? `${r.lead_h}h` : '—'}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mc-note">
        仅当标签与模型输入独立、事件切分无泄漏且配置/数据版本可追溯时，上述指标才视为有效的样本外证据。
      </div>
    </section>
  )
}
