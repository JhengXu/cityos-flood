import { useEffect, useRef, useState } from 'react'

/**
 * AnimatedNumber — 数值滚动动画（大数字变化时平滑过渡）
 * 用于灾种卡等关键指标，提升指挥中心"活"感
 */
export default function AnimatedNumber({ value, duration = 800, format = (v) => v, className = '' }) {
  const [display, setDisplay] = useState(0)
  const prevRef = useRef(0)
  const rafRef = useRef(null)

  useEffect(() => {
    const target = typeof value === 'number' ? value : parseFloat(value) || 0
    const start = prevRef.current
    if (Math.abs(target - start) < 0.01) {
      setDisplay(target)
      prevRef.current = target
      return
    }
    const t0 = performance.now()
    const tick = (now) => {
      const p = Math.min((now - t0) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3) // easeOutCubic
      const cur = start + (target - start) * eased
      setDisplay(cur)
      if (p < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        prevRef.current = target
      }
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [value, duration])

  return <span className={className}>{format(display)}</span>
}
