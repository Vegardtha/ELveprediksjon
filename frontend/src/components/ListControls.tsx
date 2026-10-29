import type { Filter, Sort } from '../filter'

interface Props {
  filter: Filter
  onChange: (f: Filter) => void
  shown: number
  total: number
  dayLabel: string | null
}

export function ListControls({ filter, onChange, shown, total, dayLabel }: Props) {
  const set = (p: Partial<Filter>) => onChange({ ...filter, ...p })
  return (
    <div className="list-controls">
      <div className="list-controls-row">
        <select aria-label="Sortering" value={filter.sort} onChange={(e) => set({ sort: e.target.value as Sort })}>
          <option value="name">Alfabetisk</option>
          <option value="best">{dayLabel ? `Best ${dayLabel}` : 'Best de neste 3 dagene'}</option>
          <option value="basin">Vassdrag</option>
        </select>
        <label>
          <input type="checkbox" checked={filter.paddleableOnly} onChange={(e) => set({ paddleableOnly: e.target.checked })} />
          {dayLabel ? 'Padlbart da' : 'Padlbart snart'}
        </label>
        <label>
          <input type="checkbox" checked={filter.hideRegulated} onChange={(e) => set({ hideRegulated: e.target.checked })} />
          Skjul demningsstyrte
        </label>
        <span className="muted count">{shown === total ? `${total} seksjoner` : `${shown} av ${total}`}</span>
      </div>
    </div>
  )
}
