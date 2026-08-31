import WorldModelPanel from './WorldModelPanel.jsx'

/**
 * WorldModelPage — 世界模型推演页（v5 壳）
 * 复用 WorldModelPanel 逻辑，套新页容器
 */
export default function WorldModelPage({ predictData }) {
  return (
    <div className="legacy-wrap">
      <WorldModelPanel predictData={predictData} />
    </div>
  )
}
