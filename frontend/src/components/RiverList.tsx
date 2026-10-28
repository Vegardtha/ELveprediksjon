import { fmtQ, STATUS } from '../status'
import type { River } from '../types'
import { RegulationBadge } from './Badges'
import { DayStrip } from './DayStrip'
import { basin } from '../filter'

interface Props {
  rivers: River[]
  selected: string | null
  onSelect: (id: string) => void
  grouped?: boolean
}

export function RiverList({ rivers, selected, onSelect, grouped }: Props) {
  return (
    <ul className="river-list">
      {rivers.map((r, i) => (
        <li key={r.id}>
          {grouped && basin(r) !== (i > 0 ? basin(rivers[i - 1]) : null) && <h2 className="list-group">{basin(r)}</h2>}
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
      {rivers.length === 0 && <li className="muted empty">Ingen elver passer filteret.</li>}
    </ul>
  )
}
