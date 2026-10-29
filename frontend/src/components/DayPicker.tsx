import { PADDLEABLE, fmtDate, fmtWeekday, statusOn } from '../status'
import type { River } from '../types'

interface Props {
  rivers: River[]
  day: number
  onChange: (day: number) => void
}

/** Velger nå eller en av prognosedagene. Søylen viser hvor mange seksjoner som er padlbare den dagen. */
export function DayPicker({ rivers, day, onChange }: Props) {
  const dates = rivers[0]?.days.map((d) => d.date) ?? []
  const count = (i: number) => rivers.filter((r) => PADDLEABLE.includes(statusOn(r, i)!)).length
  const opts = [-1, ...dates.map((_, i) => i)].map((i) => ({ i, n: count(i) }))
  const max = Math.max(1, ...opts.map((o) => o.n))
  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="days" role="radiogroup" aria-label="Vis vannføring for">
      {opts.map(({ i, n }) => {
        const date = dates[i]
        const wd = i < 0 ? '' : fmtWeekday(date)
        const label = i < 0 ? 'Nå' : date.slice(0, 10) === today ? 'I dag' : wd[0].toUpperCase() + wd.slice(1)
        return (
          <button
            key={i}
            role="radio"
            aria-checked={i === day}
            className={`day ${i === day ? 'on' : ''}`}
            onClick={() => onChange(i)}
            title={`${i < 0 ? 'Siste måling' : `${fmtWeekday(date)} ${fmtDate(date)}`}: ${n} padlbare seksjoner`}
          >
            <span className="day-bar" aria-hidden="true"><i style={{ height: `${(100 * n) / max}%` }} /></span>
            <span className="day-wd">{label}</span>
            <span className="day-n">{n}</span>
          </button>
        )
      })}
    </div>
  )
}
