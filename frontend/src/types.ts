export type Status = 'dry' | 'low' | 'min-opt' | 'opt-max' | 'high' | 'impossible'
export type Regulation = 'regulated' | 'partly' | 'unregulated' | 'unknown'
export type LatLng = [number, number]

export interface Thresholds {
  minimum: number
  optimum: number
  maximum: number
  impossible: number
  source: string
}

export interface Day {
  date: string
  p10: number
  p50: number
  p90: number
  status: Status
  prob_paddleable: number
  prob_optimal: number
}

export interface River {
  id: string
  name: string
  grade: string | null
  station: string
  station_name: string | null
  regulation: Regulation
  regulation_note: string | null
  approximate: boolean
  thresholds: Thresholds
  putin: LatLng | null
  takeout: LatLng | null
  station_pos: LatLng
  nokken_url: string | null
  q_now: number | null
  q_now_time: string | null
  status_now: Status | null
  days: Day[]
}

export interface RiverDetail extends River {
  skill: { horizon: number; NSE: number; F1_paddleable: number }[]
  skill_hourly: { hours: number; NSE: number; NSE_persistence: number }[]
}

export interface ForecastDay extends Day {
  issue_date: string
  horizon: number
  rr_forecast: number | null
  tm_forecast: number | null
}

export interface Observation {
  time: string
  q: number
}

export interface Meta {
  run: { run_at?: string }
  issue_date: string
  attribution: { name: string; what: string; license: string; url: string }[]
}

export interface HourlyForecast {
  issue_time: string
  time: string
  k: number
  p10: number
  p50: number
  p90: number
  status: Status
  prob_paddleable: number
  rr: number | null
}

/** Seksjoner tegnet langs elva (OpenStreetMap), koordinater som [lon, lat]. */
export interface SectionLines {
  features: { properties: { id: string }; geometry: { coordinates: [number, number][] } }[]
}
