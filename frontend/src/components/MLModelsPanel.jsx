import { useEffect, useState } from 'react'
import { fetchJSON } from '../api'

/**
 * MLModelsPanel — 本地训练监督模型面板
 * 展示三个真实标签训练的模型及其验证指标
 */
export default function MLModelsPanel() {
  const [metrics, setMetrics] = useState(null)
  const [test, setTest] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    fetchJSON('/api/ml/metrics').then(setMetrics).catch((e) => setErr(e.message))
  }, [])

  async function runFloodTest() {
    setTest('加载中…')
    try {
      const r = await fetchJSON('/api/ml/flood-spatial?lat=22.538&lon=114.058')
      const r2 = await fetchJSON('/api/ml/flood-spatial?lat=22.65&lon=113.88')
      setTest({
        futian: r.flood_risk_prob,
        baoan: r2.flood_risk_prob,
      })
    } catch (e) {
      setTest({ error: e.message })
    }
  }

  async function runWaveTest() {
    setTest('加载中…')
    try {
      // 模拟山竹台风状态（距深圳 150km, 85kt）
      const r = await fetchJSON('/api/ml/wave?tc_lat=21.5&tc_lon=113.5&wind_kt=85&pres_hpa=955&hours=18')
      setTest({ swh: r.predicted_swh_m, dist: r.tc_dist_km })
    } catch (e) {
      setTest({ error: e.message })
    }
  }

  async function runSlideTest() {
    setTest('加载中…')
    try {
      const r = await fetchJSON('/api/ml/landslide-warning?rain_24h=120&rain_72h=200&rain_168h=280&rain_max24h=35')
      setTest({ prob: r.warning_prob })
    } catch (e) {
      setTest({ error: e.message })
    }
  }

  if (err) return <div className="card"><div className="err-box">⚠ {err}</div></div>
  if (!metrics) return <div className="card"><div className="loading">加载模型指标…</div></div>

  const fs = metrics.flood_spatial || {}
  const wt = metrics.wave_typhoon || {}
  const lw = metrics.landslide_warning || {}

  return (
    <div className="card ml-panel">
      <div className="panel-title">
        🤖 本地监督学习模型（真实标签训练 · 非物理代理）
        <span className="ml-sub">训练脚本：shenzhen-flood/scripts/ml/ · 模型：HistGradientBoosting</span>
      </div>

      <div className="ml-models">
        {/* 模型① */}
        <div className="ml-model">
          <div className="mlm-head">① 内涝空间风险</div>
          <div className="mlm-tags">
            <span className="tag real">真实标签：206 官方易涝点</span>
            <span className="tag">空间分块 5-fold CV</span>
          </div>
          {fs.model ? (
            <>
              <div className="mlm-metric">
                <span>空间 CV AUC</span>
                <b>{fs.spatial_cv_auc} ±{fs.spatial_cv_auc_std}</b>
              </div>
              <div className="mlm-metric"><span>Holdout AUC</span><b>{fs.holdout_auc}</b></div>
              <div className="mlm-metric small"><span>样本</span><b>{fs.n_samples}（正{fs.n_positive}）</b></div>
              <button className="mlm-btn" onClick={runFloodTest}>实测：福田CBD vs 宝安沿海</button>
            </>
          ) : <div className="mlm-pending">模型未加载</div>}
        </div>

        {/* 模型③ */}
        <div className="ml-model">
          <div className="mlm-head">③ 台风→近岸波高</div>
          <div className="mlm-tags">
            <span className="tag real">真实标签：CMEMS 卫星同化波高</span>
            <span className="tag">Leave-One-Event-Out</span>
          </div>
          {wt.model ? (
            <>
              <div className="mlm-metric"><span>全量 R²</span><b>{wt.full_r2}</b></div>
              <div className="mlm-metric small warn">
                <span>跨事件 LOEO R²</span>
                <b>{wt.loeo_r2_mean} ⚠ 仅事件内有效</b>
              </div>
              <div className="mlm-metric small"><span>样本</span><b>{wt.n_samples}（3事件×3点）</b></div>
              <button className="mlm-btn" onClick={runWaveTest}>实测：模拟台风（150km/85kt）</button>
            </>
          ) : <div className="mlm-pending">模型未加载</div>}
        </div>

        {/* 模型② */}
        <div className="ml-model">
          <div className="mlm-head">② 滑坡预警发布</div>
          <div className="mlm-tags">
            <span className="tag real">真实标签：905 条官方预警（2012-2026）</span>
            <span className="tag">时间外验证</span>
          </div>
          {lw.model ? (
            <>
              <div className="mlm-metric"><span>时间外 AUC（2023-26 测试）</span><b>{lw.test_auc}</b></div>
              <div className="mlm-metric small"><span>样本</span><b>{lw.n_samples}（正{lw.n_positive}）</b></div>
              <button className="mlm-btn" onClick={runSlideTest}>实测：暴雨场景（24h 120mm）</button>
            </>
          ) : (
            <div className="mlm-pending">
              ERA5 特征下载中…<br />
              <span className="small">（14 年逐日土壤湿度/降雨，约 15 分钟）</span>
            </div>
          )}
        </div>
      </div>

      {test && typeof test === 'object' && (
        <div className="ml-test-result">
          {test.error ? `⚠ ${test.error}` : (
            test.flood_risk_prob !== undefined || test.futian !== undefined ? (
              <>实测结果 — 福田CBD: <b>{(test.futian * 100).toFixed(2)}%</b> · 宝安沿海: <b>{(test.baoan * 100).toFixed(2)}%</b> 内涝风险</>
            ) : test.swh !== undefined ? (
              <>实测结果 — 台风距 {test.dist}km → 预测波高 <b>{test.swh}m</b></>
            ) : test.prob !== undefined ? (
              <>实测结果 — 24h 120mm 暴雨 → 预警发布概率 <b>{(test.prob * 100).toFixed(1)}%</b></>
            ) : null
          )}
        </div>
      )}
      {typeof test === 'string' && <div className="ml-test-result">{test}</div>}
    </div>
  )
}
