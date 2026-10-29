import type { River } from './types'

// Hovednummeret i NVE-stasjonsnummeret er vassdraget (REGINE).
const BASINS: Record<string, string> = {
  '2': 'Glomma og Gudbrandsdalen',
  '6': 'Oslo og Bærum',
  '7': 'Oslo og Bærum',
  '8': 'Oslo og Bærum',
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
// sjanse for padlbart på valgt dag, eller beste av de neste tre dagene når ingen dag er valgt (`day` = -1)
const best = (r: River, day: number) =>
  day >= 0 ? r.days[day]?.prob_paddleable ?? 0 : Math.max(0, ...r.days.slice(0, 3).map((d) => d.prob_paddleable))

export function applyFilter(rivers: River[], f: Filter, day = -1): River[] {
  const q = norm(f.q.trim())
  const out = rivers.filter(
    (r) =>
      (!q || norm(`${r.name} ${r.station_name ?? ''} ${basin(r)}`).includes(q)) &&
      (!f.hideRegulated || r.regulation !== 'regulated') &&
      (!f.paddleableOnly || best(r, day) >= 0.5),
  )
  const byName = (a: River, b: River) => a.name.localeCompare(b.name, 'nb')
  if (f.sort === 'name') return out.sort(byName)
  if (f.sort === 'basin') return out.sort((a, b) => basin(a).localeCompare(basin(b), 'nb') || byName(a, b))
  return out.sort((a, b) => best(b, day) - best(a, day) || byName(a, b))
}
