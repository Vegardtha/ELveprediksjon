import type { Regulation, River, Status } from './types'

// Ordnet skala fra for lite til for mye. Farge bærer aldri betydning alene – alltid med tekst.
// `rank` styrer tegnerekkefølgen på kartet: padlbare seksjoner ligger øverst.
export const STATUS: Record<Status, { label: string; short: string; color: string; rank: number }> = {
  dry: { label: 'For lite vann', short: 'Tørt', color: '#9a9890', rank: 1 },
  low: { label: 'Lavt, under minimum', short: 'Lavt', color: '#6fa6e6', rank: 2 },
  'min-opt': { label: 'Padlbart, i lavkant', short: 'Padlbart', color: '#86c95a', rank: 5 },
  'opt-max': { label: 'Optimalt', short: 'Optimalt', color: '#14983a', rank: 6 },
  high: { label: 'Høyt', short: 'Høyt', color: '#ef8a3e', rank: 4 },
  impossible: { label: 'For mye vann', short: 'For mye', color: '#d23a3a', rank: 3 },
}

export const STATUS_ORDER: Status[] = ['dry', 'low', 'min-opt', 'opt-max', 'high', 'impossible']
export const PADDLEABLE: Status[] = ['min-opt', 'opt-max']

/** Status nå (`day` = -1) eller for prognosedag `day`. */
export const statusOn = (r: River, day: number): Status | null => (day < 0 ? r.status_now : r.days[day]?.status ?? null)

export const REGULATION: Record<Regulation, { label: string; long: string }> = {
  regulated: { label: 'Demningsstyrt', long: 'Vannføringen styres i stor grad av slipp fra demning' },
  partly: { label: 'Delvis regulert', long: 'Noe regulering i nedbørfeltet' },
  unregulated: { label: 'Uregulert', long: 'Naturlig vannføring' },
  unknown: { label: 'Regulering ukjent', long: 'NVE mangler reguleringsdata' },
}

export const fmtQ = (q: number | null | undefined) =>
  q == null ? '–' : q >= 100 ? q.toFixed(0) : q >= 10 ? q.toFixed(1) : q.toFixed(2)

const day = (iso: string) => new Date(iso.slice(0, 10) + 'T12:00:00')
export const fmtWeekday = (iso: string) => day(iso).toLocaleDateString('nb-NO', { weekday: 'short' }).replace('.', '')
export const fmtDate = (iso: string) => day(iso).toLocaleDateString('nb-NO', { day: 'numeric', month: 'short' })
export const fmtTime = (iso: string) =>
  new Date(/[Z+]/.test(iso.slice(10)) ? iso : iso + 'Z').toLocaleString('nb-NO', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
export const pct = (p: number) => `${Math.round(p * 100)} %`
