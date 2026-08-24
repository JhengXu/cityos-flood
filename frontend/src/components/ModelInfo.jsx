import { levelColor, LEVEL_LABELS } from '../api'

function valueOr(value, fallback = '—') {
  return value === null || value === undefined || value === '' ? fallback : value
}

export default function ModelInfo({ data }) {
  const m = data.model || {}
  const weights = m.hybrid_weights || {}
  const legacyOnly = Object.keys(weights).length > 0 && !(
    m.family || m.architecture || m.ensemble_members || m.n_members
    || m.assimilation || m.state_variable || m.mass_conservative
  )

  if (legacyOnly) {
    const labels = m.hybrid_feature_labels || {}
    return (
      <section className="model card">
        <div className="card-h">
          旧概率模型兼容视图
          <span className="hint">{m.name} · 仅供旧接口过渡，不作为准确性证据</span>
        </div>
        <div className="status-banner limited">
          <b>当前响应尚未包含集合水深字段</b>
          <span>页面暂时回退到旧风险概率；请检查后端状态空间模型是否已启用。</span>
        </div>
        <div className="model-body">
          <div className="model-col">
            <div className="mc-h">旧线性项（非主模型）</div>
            {Object.entries(weights).map(([key, value]) => (
              <div className="mc-row" key={key}><span>{labels[key] || key}</span><span className="num">{value}</span></div>
            ))}
          </div>
          <div className="model-col">
            <div className="mc-h">限制</div>
            <div className="mc-note">{m.notes || '旧模型由同一物理规则生成的数据训练，不能当作独立灾情预测验证。'}</div>
          </div>
        </div>
      </section>
    )
  }

  const readiness = data.data_readiness || data.observation_readiness || data.data_quality || {}
  const qualityFlags = Array.isArray(data.quality_flags) ? data.quality_flags : []
  const thresholds = m.thresholds_mm || m.depth_thresholds_mm
    || m.thresholds_m?.map((value) => Number(value) * 1000)
    || data.thresholds_mm || [50, 150, 300, 500]
  const provenanceRaw = m.parameter_provenance || m.provenance || data.hazard_model?.provenance || data.parameter_provenance || {}
  const provenance = provenanceRaw && typeof provenanceRaw === 'object' ? provenanceRaw : { source: provenanceRaw }
  const ensembleMembers = m.members || m.ensemble_members || m.n_members || m.ensemble?.members || data.ensemble_members
  const topologyEdges = m.topology?.edges
  const edgeCount = m.edge_count || m.edges?.length || (Array.isArray(topologyEdges) ? topologyEdges.length : topologyEdges)
  const modelName = m.name || data.hazard_model?.name || '分区守恒图状态空间集合模型'
  const assimilationRaw = m.assimilation?.method || m.assimilation
  const assimilation = typeof assimilationRaw === 'string' ? assimilationRaw : '确定性局地 EnSRF（有时效观测时）'
  const conservative = m.mass_conservative ?? m.mass_balance?.all_members_conservative

  return (
    <section className="model card">
      <div className="card-h">
        核心预测模型
        <span className="hint">{modelName}</span>
      </div>
      <div className="model-body">
        <div className="model-col">
          <div className="mc-h">状态与动力学</div>
          <div className="mc-row"><span>模型族</span><span className="num">{valueOr(m.family || m.architecture, '物理约束灰箱')}</span></div>
          <div className="mc-row"><span>主状态</span><span className="num">{valueOr(m.state_variable || m.state, '存水体积 m³ → 水深 mm')}</span></div>
          <div className="mc-row"><span>更新步长</span><span className="num">{valueOr(m.dt_hours || m.time_step_hours, 1)} h</span></div>
          <div className="mc-row"><span>空间路由边</span><span className="num">{valueOr(edgeCount, '有向下泄图')}</span></div>
          <div className="mc-row"><span>质量守恒</span><span className={`num ${conservative === false ? 'hot' : 'ok'}`}>{conservative === false ? '未通过' : (conservative === true ? '集合全员通过' : '逐步审计')}</span></div>
        </div>

        <div className="model-col">
          <div className="mc-h">不确定性与观测</div>
          <div className="mc-row"><span>集合成员</span><span className="num">{valueOr(ensembleMembers, '多参数成员')}</span></div>
          <div className="mc-row"><span>主输出</span><span className="num">P10 / P50 / P90 水深</span></div>
          <div className="mc-row"><span>超阈概率</span><span className="num">P(d≥阈值)</span></div>
          <div className="mc-row"><span>同化方法</span><span className="num">{assimilation}</span></div>
          <div className="mc-row"><span>观测门控</span><span className="num">{readiness.fresh_observations ? '已注入' : '时效 + 质控 + 空间映射'}</span></div>
        </div>

        <div className="model-col">
          <div className="mc-h">积水深度分级</div>
          <div className="levels depth-levels">
            {LEVEL_LABELS.map((label, i) => (
              <span key={label} className="lv" style={{ background: levelColor(i) }}>
                {label}{i > 0 && thresholds[i - 1] != null ? ` ≥${thresholds[i - 1]}mm` : ''}
              </span>
            ))}
          </div>
          <div className="mc-note">
            {m.limitations || m.notes || data.hazard_model?.note || '当前为行政区尺度灰箱水文模型；权威子流域、管网拓扑与长时段灾情真值齐备前，不应视为街道级工程预报。'}
          </div>
        </div>
      </div>

      {qualityFlags.length > 0 && (
        <div className="status-banner limited">
          <b>数据质量标记</b>
          <span>{qualityFlags.map((flag) => {
            const code = typeof flag === 'string' ? flag : (flag.message || flag.code || JSON.stringify(flag))
            return ({
              uncalibrated_parameters: '参数尚未由独立事件校准',
              district_scale_not_street_depth: '行政区代表性水深，不是街点实测',
              synthetic_rainfall_fallback: '降雨使用后备合成过程',
              no_fresh_water_level_assimilation: '无三小时内可同化水位观测',
            })[code] || code
          }).join(' · ')}</span>
        </div>
      )}

      {Object.keys(provenance).length > 0 && (
        <div className="parameter-strip">
          <b>参数来源</b>
          {Object.entries(provenance).slice(0, 6).map(([key, value]) => (
            <span key={key} title={String(value)}>{key}：{String(value)}</span>
          ))}
        </div>
      )}
    </section>
  )
}
