import { STATUS, fmtDate, fmtQ, fmtWeekday, pct } from '../status'
import type { Day } from '../types'

/** Ni dager som fargede celler med ukedag og sannsynlighet for padlbart. `active` markerer valgt dag. */
export function DayStrip({ days, compact = false, active = -1 }: { days: Day[]; compact?: boolean; active?: number }) {
  return (
    <div className={`strip ${compact ? 'compact' : ''}`} role="list">
      {days.map((d, i) => (
        <div
          key={d.date}
          role="listitem"
          className={`cell ${i === active ? 'on' : ''}`}
          title={`${fmtWeekday(d.date)} ${fmtDate(d.date)}: ${STATUS[d.status].label}, ${fmtQ(d.p50)} m³/s (${fmtQ(d.p10)}–${fmtQ(d.p90)}). Sjanse for padlbart: ${pct(d.prob_paddleable)}`}
        >
          <span className="wd">{fmtWeekday(d.date)}</span>
          <span className="sq" style={{ background: STATUS[d.status].color }} />
          <span className="pp">{Math.round(d.prob_paddleable * 100)}</span>
        </div>
      ))}
    </div>
  )
}
