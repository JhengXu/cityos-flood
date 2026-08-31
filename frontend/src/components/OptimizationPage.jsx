import OntologyPanel from './OntologyPanel.jsx'
import WamOptimizationPanel from './WamOptimizationPanel.jsx'
import DecisionPanel from './DecisionPanel.jsx'

/**
 * OptimizationPage — 自主优化 WAM 页（v5 壳）
 * 城市本体（脆弱性底座）+ WAM 决策闭环，纵向排布
 */
export default function OptimizationPage({ predictData }) {
  return (
    <div className="legacy-wrap">
      <DecisionPanel />
      <OntologyPanel />
      <WamOptimizationPanel predictData={predictData} />
    </div>
  )
}
