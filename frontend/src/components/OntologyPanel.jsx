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

  return (
    <section className="card stage">
      <div className="card-h">
        城市 3D 本体 · Ontology
        <span className="hint">{data.model}</span>
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
      <div className="mc-note">{data.note}</div>
    </section>
  )
}
