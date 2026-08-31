// 轻量可重试 fetch，避免后端重启/短暂不可用时前端白屏报错
export async function fetchJSON(url, { retries = 2, backoff = 250 } = {}) {
  let last
  for (let i = 0; i < retries; i++) {
    try {
      const r = await fetch(url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return await r.json()
    } catch (e) {
      last = e
      await new Promise((res) => setTimeout(res, backoff * (i + 1)))
    }
  }
  throw last
}

export async function getPredict(forecastDays = 3, forecastRunId = null) {
  const run = forecastRunId ? `&forecast_run_id=${encodeURIComponent(forecastRunId)}` : ''
  const r = await fetchJSON(`/api/predict?forecast_days=${forecastDays}${run}`)
  if (!r || r.error) throw new Error('预测接口请求失败（后端是否已启动？）')
  return r
}

export function fmtTime(iso) {
  if (!iso) return ''
  const s = iso.replace('T', ' ')
  return `${s.slice(5, 10)} ${s.slice(11, 16)}`.trim()
}

export const LEVEL_COLORS = ['#1f7a4d', '#c9b458', '#e08a1e', '#d6452a', '#b3122b']
export const LEVEL_LABELS = ['无', '低', '中', '高', '极高']

export function levelColor(level) {
  return LEVEL_COLORS[level] || LEVEL_COLORS[0]
}

// 新状态空间模型以积水深度及其集合分位数作为主输出。下面的读取器同时
// 兼容早期概率接口，避免后端滚动升级期间页面因字段名变化而失效。
function finite(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function firstFinite(...values) {
  for (const value of values) {
    const number = finite(value)
    if (number !== null) return number
  }
  return null
}

function nestedValue(point, paths) {
  for (const path of paths) {
    let value = point
    for (const key of path) value = value?.[key]
    const number = finite(value)
    if (number !== null) return number
  }
  return null
}

export function depthQuantilesM(point = {}) {
  const fromMeters = (q) => nestedValue(point, [
    [`depth_${q}_m`], [`${q}_depth_m`], ['depth_m', q], ['water_depth_m', q], ['depth', `${q}_m`],
    ['uncertainty', `depth_${q}_m`],
  ])
  const fromMillimeters = (q) => nestedValue(point, [
    [`depth_${q}_mm`], [`${q}_depth_mm`], ['depth_mm', q], ['depth', `${q}_mm`],
    ['uncertainty', `depth_${q}_mm`],
  ])
  const read = (q) => {
    const meters = fromMeters(q)
    if (meters !== null) return meters
    const millimeters = fromMillimeters(q)
    return millimeters === null ? null : millimeters / 1000
  }

  let p10 = read('p10')
  let p50 = read('p50')
  let p90 = read('p90')
  const pointDepth = firstFinite(point.depth_m, point.water_depth_m)
  const pointDepthMm = firstFinite(point.depth_mm, point.water_depth_mm)
  if (p50 === null) p50 = pointDepth ?? (pointDepthMm === null ? null : pointDepthMm / 1000)
  if (p10 === null && p50 !== null) p10 = p50
  if (p90 === null && p50 !== null) p90 = p50
  return { p10, p50, p90, available: p50 !== null }
}

function normalizedProbability(value) {
  const number = finite(value)
  if (number === null) return null
  return Math.max(0, Math.min(1, number > 1 && number <= 100 ? number / 100 : number))
}

export function exceedanceProbability(point = {}, thresholdM = 0.15) {
  const thresholdMm = Math.round(thresholdM * 1000)
  const decimal = String(thresholdM)
  const token = decimal.replace('.', '_')
  const maps = [
    point.threshold_prob,
    point.threshold_probability,
    point.threshold_probabilities,
    point.exceedance_probability,
    point.exceedance_probabilities,
  ].filter((value) => value && typeof value === 'object')
  const keys = [
    decimal, `${decimal}m`, String(thresholdMm), `${thresholdMm}mm`,
    `gt_${token}m`, `ge_${token}m`, `depth_ge_${thresholdMm}mm`, `p_ge_${thresholdMm}mm`,
  ]
  for (const map of maps) {
    for (const key of keys) {
      const probability = normalizedProbability(map[key])
      if (probability !== null) return probability
    }
  }

  const explicitProbability = normalizedProbability(firstFinite(
    point[`prob_depth_ge_${thresholdMm}mm`],
    point[`prob_ge_${thresholdMm}mm`],
    point[`exceedance_${thresholdMm}mm`],
  ))
  if (explicitProbability !== null) return explicitProbability

  const definition = String(point.probability_definition || point.surrogate?.probability_definition || '')
    .toLowerCase()
  const compatibleLegacyProbability = Math.abs(thresholdM - 0.15) < 1e-9
    && definition.includes('0.15')
    && definition.includes('depth')
  return compatibleLegacyProbability
    ? normalizedProbability(firstFinite(point.prob, point.surrogate?.prob))
    : null
}

export function formatDepthM(value, digits = 2) {
  const number = finite(value)
  return number === null ? '—' : `${number.toFixed(digits)}m`
}

export function formatPercent(value, digits = 0) {
  const probability = normalizedProbability(value)
  return probability === null ? '—' : `${(probability * 100).toFixed(digits)}%`
}

// 可信度来源标签（理论 §16：observed/estimated/assumed/simulated）
export const PROVENANCE_COLORS = {
  observed: '#1f7a4d',
  estimated: '#145BFF',
  assumed: '#c9b458',
  simulated: '#b3122b',
}
export const PROVENANCE_LABELS = {
  observed: '观测',
  estimated: '估计/校准',
  assumed: '假设',
  simulated: '模拟',
}
export function provColor(tag) {
  if (!tag) return 'rgba(255,255,255,.35)'
  const t = String(tag).split(/[ (]/)[0].toLowerCase()
  return PROVENANCE_COLORS[t] || 'rgba(255,255,255,.35)'
}
export function provLabel(tag) {
  if (!tag) return tag || ''
  const t = String(tag).split(/[ (]/)[0].toLowerCase()
  return PROVENANCE_LABELS[t] || tag
}

export async function getSimulate(params = {}) {
  const q = new URLSearchParams(params).toString()
  const r = await fetch(`/api/simulate?${q}`)
  if (!r.ok) throw new Error('情景推演失败')
  return r.json()
}

export async function postSimulate(scenario = {}) {
  const r = await fetch('/api/simulate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(scenario),
  })
  if (!r.ok) throw new Error('情景推演失败')
  return r.json()
}

export async function postDispatch(payload = {}) {
  const r = await fetch('/api/dispatch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error('预警下发失败')
  return r.json()
}

export async function getAlerts(limit = 50) {
  const r = await fetch(`/api/alerts?limit=${limit}`)
  if (!r.ok) throw new Error('获取预警记录失败')
  return r.json()
}

export async function getEvents() {
  const r = await fetch('/api/events')
  if (!r.ok) throw new Error('获取历史事件失败')
  return r.json()
}

export async function getVerify() {
  const r = await fetch('/api/verify')
  if (!r.ok) throw new Error('获取验证报告失败')
  return r.json()
}

export async function getOntology() {
  const r = await fetch('/api/ontology')
  if (!r.ok) throw new Error('获取城市本体失败')
  return r.json()
}

export async function getRoles() {
  const r = await fetch('/api/roles')
  if (!r.ok) throw new Error('获取 AI 角色失败')
  return r.json()
}

export async function getCurrent() {
  const r = await fetch('/api/data/current')
  if (!r.ok) throw new Error('获取实时数据失败')
  return r.json()
}

export async function uploadData(file) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch('/api/data/upload', { method: 'POST', body: fd })
  if (!r.ok) throw new Error('上传失败')
  return r.json()
}

export async function manualForecast(payload) {
  const r = await fetch('/api/forecast/manual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error('手动预测失败')
  return r.json()
}

export async function getBenchmark() {
  const r = await fetch('/api/benchmark')
  if (!r.ok) throw new Error('获取模型对比失败')
  return r.json()
}

export function exportReport() {
  window.open('/api/verify/export', '_blank')
}

// ============ 世界模型（同学版本扩展）============
export async function getSpatial() {
  return fetchJSON('/api/spatial')
}

export async function getAccessibility(params = {}) {
  const q = new URLSearchParams(params).toString()
  return fetchJSON(`/api/accessibility?${q}`)
}

export async function getCounterfactual(params = {}) {
  const q = new URLSearchParams(params).toString()
  return fetchJSON(`/api/counterfactual?${q}`)
}

export async function getAssimilate(params = {}) {
  const q = new URLSearchParams(params).toString()
  return fetchJSON(`/api/assimilate?${q}`)
}

export async function getRealtimeAssimilate(params = {}) {
  const q = new URLSearchParams(params).toString()
  return fetchJSON(`/api/assimilate/realtime?${q}`)
}

// ============ 自主优化 WAM（安全建议模式）============
export async function postWamOptimize(payload = {}) {
  const r = await fetch('/api/wam/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) {
    let detail = ''
    try {
      const body = await r.json()
      detail = body?.detail ? `：${typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)}` : ''
    } catch {
      // Keep the concise HTTP fallback when the server did not return JSON.
    }
    throw new Error(`WAM 动作优化失败（HTTP ${r.status}）${detail}`)
  }
  return r.json()
}

// ============ 实时抓取平台数据 ============
export async function getPlatformRealtime() {
  return fetchJSON('/api/platform/realtime')
}

export async function getPlatformGeocode(q) {
  return fetchJSON(`/api/platform/geocode?q=${encodeURIComponent(q)}`)
}

export async function getStreetRisk(forecastDays = 3, forecastRunId = null) {
  const run = forecastRunId ? `&forecast_run_id=${encodeURIComponent(forecastRunId)}` : ''
  return fetchJSON(`/api/risk/street?forecast_days=${forecastDays}${run}`)
}

export async function getGridRisk(forecastDays = 3, res = 0.018, forecastRunId = null) {
  const run = forecastRunId ? `&forecast_run_id=${encodeURIComponent(forecastRunId)}` : ''
  const payload = await fetchJSON(`/api/risk/grid?forecast_days=${forecastDays}&res=${res}${run}`)
  const encoding = payload?.timeseries_encoding
  if (encoding?.layout === 'cell-major' && payload.risk_u8_b64 && payload.depth_mm_u16le_b64) {
    const decodeBytes = (encoded) => {
      const binary = atob(encoded)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
      return bytes
    }
    payload._riskU8 = decodeBytes(payload.risk_u8_b64)
    payload._depthU16LEBytes = decodeBytes(payload.depth_mm_u16le_b64)
    // Release the much larger UTF-16 base64 strings after decoding.
    delete payload.risk_u8_b64
    delete payload.depth_mm_u16le_b64
  }
  return payload
}

export async function getGridImageBBox(forecastDays = 3, forecastRunId = null, hourIndex = null, signal = undefined) {
  const params = new URLSearchParams({ res: '0.0045', forecast_days: String(forecastDays) })
  if (forecastRunId) params.set('forecast_run_id', forecastRunId)
  if (hourIndex !== null && hourIndex !== undefined) params.set('hour_index', String(hourIndex))
  const url = `/api/risk/grid/image?${params.toString()}`
  const r = await fetch(url, { method: 'HEAD', signal })
  if (!r.ok) throw new Error(`500m 图层预检失败（HTTP ${r.status}）`)
  const bounds = bboxFromHeaders(r)
  if (Object.values(bounds).some((value) => !Number.isFinite(value))) {
    throw new Error('500m 图层缺少有效空间范围')
  }
  const responseRunId = r.headers.get('X-Forecast-Run-Id') || null
  if (forecastRunId && responseRunId !== forecastRunId) {
    throw new Error('500m 图层预报快照与当前页面不一致')
  }
  const temporalSlice = r.headers.get('X-Temporal-Slice') || null
  const expectedSlice = hourIndex === null || hourIndex === undefined ? 'horizon-peak' : `hour-${hourIndex}`
  if (temporalSlice && temporalSlice !== expectedSlice) {
    throw new Error('500m 图层时次与当前时间轴不一致')
  }
  const rasterEmptyRaw = r.headers.get('X-Raster-Empty')
  if (rasterEmptyRaw !== null && !['true', 'false'].includes(rasterEmptyRaw.toLowerCase())) {
    throw new Error('500m 图层返回了无效的空图标记')
  }
  const rasterEmpty = rasterEmptyRaw === null ? null : rasterEmptyRaw.toLowerCase() === 'true'
  const visibleCells = numberHeader(r, 'X-Visible-Cell-Count')
  if (rasterEmpty !== null && visibleCells !== null && rasterEmpty !== (visibleCells === 0)) {
    throw new Error('500m 图层空图标记与着色像元数矛盾')
  }
  return {
    url,
    ...bounds,
    visibleCells,
    totalCells: numberHeader(r, 'X-Total-Cell-Count'),
    maxDepthM: (numberHeader(r, 'X-Max-Depth-Mm') ?? 0) / 1000,
    maxProbability: numberHeader(r, 'X-Max-Probability'),
    forecastRunId: responseRunId,
    temporalSlice,
    empty: rasterEmpty ?? visibleCells === 0,
  }
}

function numberHeader(r, name) {
  const raw = r.headers.get(name)
  if (raw === null || raw.trim() === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

function bboxFromHeaders(r) {
  return {
    south: numberHeader(r, 'X-BBox-South') ?? Number.NaN,
    west: numberHeader(r, 'X-BBox-West') ?? Number.NaN,
    north: numberHeader(r, 'X-BBox-North') ?? Number.NaN,
    east: numberHeader(r, 'X-BBox-East') ?? Number.NaN,
  }
}

// ============ 全自然灾害（v4 多灾种 + 3D 场景）============
export async function getHazardsSummary() {
  return fetchJSON('/api/hazards/summary')
}

export async function getTyphoonTrack(name, sid) {
  const q = new URLSearchParams()
  if (name) q.set('name', name)
  if (sid) q.set('sid', sid)
  return fetchJSON(`/api/hazards/typhoon/track?${q.toString()}`)
}

export async function getScene3d(opts = {}) {
  const q = new URLSearchParams({
    dem_step: String(opts.demStep ?? 8),
    building_min_height: String(opts.buildingMinHeight ?? 40),
    building_limit: String(opts.buildingLimit ?? 5000),
  })
  return fetchJSON(`/api/scene3d?${q.toString()}`)
}

export const HAZARD_META = {
  typhoon: { name: '台风', icon: '🌀', color: '#4da3ff' },
  surge: { name: '风暴潮', icon: '🌊', color: '#37c8c3' },
  flood: { name: '内涝', icon: '🌧️', color: '#e08a1e' },
  landslide: { name: '山体滑坡', icon: '⛰', color: '#c26b1e' },
}

// 台风等级配色
export const TYPHOON_LEVEL_COLORS = {
  super_typhoon: '#b3122b', severe_typhoon: '#d6452a', typhoon: '#e08a1e',
  sts: '#c9b458', ts: '#7ec8e3', td: '#a8d5ba', unknown: '#888',
}
export function typhoonLevelColor(level) {
  return TYPHOON_LEVEL_COLORS[level] || '#888'
}

// ============ 多灾种链式预测 ============
export async function getCascadeTyphoon(name, sid) {
  const q = new URLSearchParams()
  if (name) q.set('name', name)
  if (sid) q.set('sid', sid)
  return fetchJSON(`/api/ml/cascade/typhoon?${q.toString()}`)
}
