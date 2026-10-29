import { fmtQ, STATUS, statusOn } from '../status'
import type { River } from '../types'
import { DamIcon } from './Badges'
import { DayStrip } from './DayStrip'
import { basin } from '../filter'

interface Props {
  rivers: River[]
  selected: string | null
  onSelect: (id: string) => void
  grouped?: boolean
  day: number
}

export function RiverList({ rivers, selected, onSelect, grouped, day }: Props) {
  return (
    <ul className="river-list">
      {rivers.map((r, i) => {
        const [river, section] = r.name.split(' – ')
        const s = statusOn(r, day)
        const q = day >= 0 ? r.days[day]?.p50 : r.q_now
        return (
          <li key={r.id}>
            {grouped && basin(r) !== (i > 0 ? basin(rivers[i - 1]) : null) && <h2 className="list-group">{basin(r)}</h2>}
            <button
              className={`river-row ${r.id === selected ? 'active' : ''}`}
              style={{ '--c': s ? STATUS[s].color : 'var(--line)' } as React.CSSProperties}
              onClick={() => onSelect(r.id)}
            >
              <div className="row-head">
                <span className="name">
                  <b>{river}</b>
                  {section && <span className="section">{section}</span>}
                </span>
                {r.grade && <span className="grade">{r.grade}</span>}
                {r.regulation === 'regulated' && (
                  <span className="reg" title="Demningsstyrt"><DamIcon size={13} /><span className="sr">Demningsstyrt</span></span>
                )}
                <span className="q">
                  {day >= 0 && <span className="approx">ca. </span>}
                  {fmtQ(q)} <small>m³/s</small>
                </span>
              </div>
              <div className="row-status">{s ? STATUS[s].label : 'Ingen måling'}</div>
              <DayStrip days={r.days} compact active={day} />
            </button>
          </li>
        )
      })}
      {rivers.length === 0 && <li className="muted empty">Ingen seksjoner passer filteret. Prøv et annet søk eller fjern avkryssingene.</li>}
    </ul>
  )
}
