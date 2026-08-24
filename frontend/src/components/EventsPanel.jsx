import { useState, useEffect } from 'react'
import { getEvents } from '../api'

export default function EventsPanel() {
  const [events, setEvents] = useState(null)
  useEffect(() => {
    getEvents()
      .then((d) => setEvents(d.events))
      .catch(() => setEvents([]))
  }, [])
  if (!events) return null
  return (
    <div className="card events">
      <div className="card-h">
        真实历史内涝事件
        <span className="hint">模型「历史内涝易发指数」的标定依据（公开报道，附出处）</span>
      </div>
      <div className="ev-list">
        {events.map((e, i) => (
          <div className="ev" key={i}>
            <div className="ev-date">{e.date}</div>
            <div className="ev-body">
              <b>{e.name}</b>
              <div className="ev-note">{e.note}</div>
              <div className="ev-src">来源：{e.source}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
