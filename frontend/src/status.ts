import type { Regulation, Status } from './types'

// Ordnet skala fra for lite til for mye. Farge bærer aldri betydning alene – alltid med tekst.
export const STATUS: Record<Status, { label: string; short: string; color: string }> = {
  dry: { label: 'For lite vann', short: 'Tørt', color: '#9a9890' },
  low: { label: 'Lavt, under minimum', short: 'Lavt', color: '#86b6ef' },
  'min-opt': { label: 'Padlbart, i lavkant', short: 'Padlbart', color: '#7cc576' },
  'opt-max': { label: 'Optimalt', short: 'Optimalt', color: '#0ca30c' },
  high: { label: 'Høyt', short: 'Høyt', color: '#ec835a' },
  impossible: { label: 'For mye vann', short: 'For mye', color: '#d03b3b' },
}

export const STATUS_ORDER: Status[] = ['dry', 'low', 'min-opt', 'opt-max', 'high', 'impossible']

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
