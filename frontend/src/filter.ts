import type { River } from './types'

// Hovednummeret i NVE-stasjonsnummeret er vassdraget (REGINE).
const BASINS: Record<string, string> = {
  '2': 'Glomma og Gudbrandsdalen',
  '6': 'Oslo og Asker',
  '7': 'Oslo og Asker',
  '8': 'Oslo og Asker',
  '12': 'Drammensvassdraget',
  '15': 'Numedalslågen',
  '16': 'Skiensvassdraget',
  '311': 'Femund og Trysil',
}
export const basin = (r: River) => BASINS[r.station.split('.')[0]] ?? 'Andre'

export type Sort = 'best' | 'name' | 'basin'
export interface Filter {
  q: string
  sort: Sort
  hideRegulated: boolean
  paddleableOnly: boolean
}
export const DEFAULT_FILTER: Filter = { q: '', sort: 'best', hideRegulated: false, paddleableOnly: false }

const norm = (s: string) => s.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
// beste sjanse for padlbart de neste tre dagene
const best = (r: River) => Math.max(0, ...r.days.slice(0, 3).map((d) => d.prob_paddleable))

export function applyFilter(rivers: River[], f: Filter): River[] {
  const q = norm(f.q.trim())
  const out = rivers.filter(
    (r) =>
      (!q || norm(`${r.name} ${r.station_name ?? ''} ${basin(r)}`).includes(q)) &&
      (!f.hideRegulated || r.regulation !== 'regulated') &&
      (!f.paddleableOnly || best(r) >= 0.5),
  )
  const byName = (a: River, b: River) => a.name.localeCompare(b.name, 'nb')
  if (f.sort === 'name') return out.sort(byName)
  if (f.sort === 'basin') return out.sort((a, b) => basin(a).localeCompare(basin(b), 'nb') || byName(a, b))
  return out.sort((a, b) => best(b) - best(a) || byName(a, b))
}
