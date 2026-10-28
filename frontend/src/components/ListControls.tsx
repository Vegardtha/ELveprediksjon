import type { Filter, Sort } from '../filter'

interface Props {
  filter: Filter
  onChange: (f: Filter) => void
  shown: number
  total: number
}

export function ListControls({ filter, onChange, shown, total }: Props) {
  const set = (p: Partial<Filter>) => onChange({ ...filter, ...p })
  return (
    <div className="list-controls">
      <input
        type="search"
        placeholder="Søk etter elv eller sted"
        aria-label="Søk etter elv"
        value={filter.q}
        onChange={(e) => set({ q: e.target.value })}
      />
      <div className="list-controls-row">
        <select aria-label="Sortering" value={filter.sort} onChange={(e) => set({ sort: e.target.value as Sort })}>
          <option value="best">Best de neste 3 dagene</option>
          <option value="name">Navn</option>
          <option value="basin">Vassdrag</option>
        </select>
        <label>
          <input type="checkbox" checked={filter.paddleableOnly} onChange={(e) => set({ paddleableOnly: e.target.checked })} />
          Padlbart snart
        </label>
        <label>
          <input type="checkbox" checked={filter.hideRegulated} onChange={(e) => set({ hideRegulated: e.target.checked })} />
          Skjul demningsstyrte
        </label>
        <span className="muted count">{shown === total ? `${total} elver` : `${shown} av ${total}`}</span>
      </div>
    </div>
  )
}
