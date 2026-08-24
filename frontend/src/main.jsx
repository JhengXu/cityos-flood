import React from 'react'
import ReactDOM from 'react-dom/client'
import 'leaflet/dist/leaflet.css'
import './styles.css'
import App from './App.jsx'

// 把任何运行时错误显示到页面上，避免“一片黑”无从排查
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { err: null }
  }
  static getDerivedStateFromError(err) {
    return { err }
  }
  componentDidCatch(err, info) {
    window.__lastErr = (err && err.stack) || String(err)
    console.error('[CITY OS] render error:', err, info)
  }
  render() {
    if (this.state.err) {
      const e = this.state.err
      return (
        <pre
          style={{
            color: '#ff8080',
            padding: 24,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontSize: 13,
            lineHeight: 1.6,
          }}
        >
          【前端渲染出错】
          {(e && e.stack) || String(e)}
        </pre>
      )
    }
    return this.props.children
  }
}

window.addEventListener('error', (ev) => {
  window.__lastErr = `${ev.message} @ ${ev.filename || ''}:${ev.lineno || ''}`
})
window.addEventListener('unhandledrejection', (ev) => {
  window.__lastErr = 'Promise rejection: ' + ((ev.reason && ev.reason.message) || ev.reason)
})

const rootEl = document.getElementById('root')
ReactDOM.createRoot(rootEl).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
)
