// 轻量可重试 fetch，避免后端重启/短暂不可用时前端白屏报错
export async function fetchJSON(url, { retries = 4, backoff = 350 } = {}) {
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

export async function getPredict(forecastDays = 3) {
  const r = await fetchJSON(`/api/predict?forecast_days=${forecastDays}`)
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

// ============ 实时抓取平台数据 ============
export async function getPlatformRealtime() {
  return fetchJSON('/api/platform/realtime')
}

export async function getPlatformGeocode(q) {
  return fetchJSON(`/api/platform/geocode?q=${encodeURIComponent(q)}`)
}

export async function getStreetRisk(forecastDays = 2) {
  return fetchJSON(`/api/risk/street?forecast_days=${forecastDays}`)
}

export async function getGridRisk(forecastDays = 2, res = 0.018) {
  return fetchJSON(`/api/risk/grid?forecast_days=${forecastDays}&res=${res}`)
}

export async function getGridImageBBox() {
  const r = await fetch('/api/risk/grid/image?res=0.0045', { method: 'HEAD' })
  return { url: `/api/risk/grid/image?res=0.0045`, ...bboxFromHeaders(r) }
}
function bboxFromHeaders(r) {
  return { south: +r.headers.get('X-BBox-South'), west: +r.headers.get('X-BBox-West'), north: +r.headers.get('X-BBox-North'), east: +r.headers.get('X-BBox-East') }
}
