import { useEffect, useState } from 'react'
import { getOntology } from '../api'

export default function OntologyPanel() {
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    getOntology().then((d) => {
      setData(d)
      setSel(d.districts[0])
    }).catch(() => setData(null))
  }, [])

  if (!data) return null
  const sorted = [...data.districts].sort((a, b) => b.vulnerability - a.vulnerability)

  const topVuln = sorted.slice(0, 3)  // 脆弱性前三

  return (
    <section className="card stage">
      <div className="card-h">
        城市 3D 本体 · Ontology
        <span className="hint">{data.model}</span>
      </div>
      <div style={{ display: 'flex', gap: 8, padding: '10px 14px', flexWrap: 'wrap', borderBottom: '1px solid var(--line-soft)' }}>
        <span className="chip" style={{ color: 'var(--danger)' }}>⚠ 脆弱性 TOP3</span>
        {topVuln.map((d, i) => (
          <span key={d.id} className="chip" style={{ cursor: 'pointer' }} onClick={() => setSel(d)}>
            {i + 1}. {d.name} {(d.vulnerability * 100).toFixed(0)}%
          </span>
        ))}
        <span className="footnote" style={{ marginLeft: 'auto' }}>点击快速定位</span>
      </div>
      <div className="onto-grid">
        <div className="onto-list">
          {sorted.map((d) => (
            <div
              key={d.id}
              className={`onto-item ${sel && sel.id === d.id ? 'on' : ''}`}
              onClick={() => setSel(d)}
            >
              <span className="oi-name">{d.name}</span>
              <span className="oi-vuln">脆弱性 {(d.vulnerability * 100).toFixed(0)}%</span>
              <span className="oi-elev">高程 {d.elevation}m</span>
            </div>
          ))}
        </div>
        {sel && (
          <div className="onto-detail">
            <div className="od-h">{sel.name} · 本底脆弱性 {(sel.vulnerability * 100).toFixed(0)}%</div>
            <div className="od-tag">{sel.tag}</div>
            <div className="od-row"><span>高程(DEM真实)</span><b>{sel.elevation} m</b></div>
            <div className="od-row"><span>排水设计标准</span><b>{sel.drainage} mm/h</b></div>
            <div className="od-row"><span>历史内涝指数(真实)</span><b>{sel.historical_index}</b></div>
            <div className="od-row"><span>临海度</span><b>{sel.coastal}</b></div>
            <div className="od-row"><span>类型</span><b>行政区 / 内涝脆弱性单元</b></div>
            <div className="od-vuln">
              {['low_lying', 'impervious', 'elevation', 'historical', 'coastal'].map((k) => (
                <div className="bar-row" key={k}>
                  <span className="bar-label">
                    {{ low_lying: '低洼', impervious: '不透水', elevation: '地势', historical: '历史', coastal: '临海' }[k]}
                  </span>
                  <span className="bar-track">
                    <span className="bar-fill" style={{ width: `${(sel.vuln_breakdown[k] || 0) * 100}%` }} />
                  </span>
                  <span className="num">{Math.round((sel.vuln_breakdown[k] || 0) * 100)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="mc-note">
        {data.note}
        <div className="mc-src">
          <b>数据来源：</b>高程/低洼 = Copernicus DEM 30m 派生 · 历史内涝指数 = 官方 2019 易涝点统计 ·
          排水标准 = 区级设计规范代理参数 · 脆弱性权重 = 研究设定（非官方标准）
        </div>
      </div>
    </section>
  )
}
