import { fmtQ, STATUS } from '../status'
import type { River } from '../types'
import { RegulationBadge } from './Badges'
import { DayStrip } from './DayStrip'

interface Props {
  rivers: River[]
  selected: string | null
  onSelect: (id: string) => void
}

export function RiverList({ rivers, selected, onSelect }: Props) {
  return (
    <ul className="river-list">
      {rivers.map((r) => (
        <li key={r.id}>
          <button className={`river-row ${r.id === selected ? 'active' : ''}`} onClick={() => onSelect(r.id)}>
            <div className="row-head">
              <span className="dot lg" style={{ background: r.status_now ? STATUS[r.status_now].color : '#ccc' }} />
              <span className="name">{r.name}</span>
              <span className="grade">{r.grade}</span>
              <RegulationBadge regulation={r.regulation} />
              <span className="q">
                {fmtQ(r.q_now)} <small>m³/s</small>
              </span>
            </div>
            <DayStrip days={r.days} compact />
          </button>
        </li>
      ))}
    </ul>
  )
}
