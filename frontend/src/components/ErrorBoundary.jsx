import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { err: null }
  }
  static getDerivedStateFromError(err) {
    return { err }
  }
  componentDidCatch(err, info) {
    console.error('[CITY OS] module error:', err, info)
  }
  render() {
    if (this.state.err) {
      return (
        this.props.fallback || (
          <div className="err-box">
            该模块加载失败：{(this.state.err && this.state.err.message) || '未知错误'}
          </div>
        )
      )
    }
    return this.props.children
  }
}
