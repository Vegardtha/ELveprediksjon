import type { ForecastDay, HourlyForecast, Meta, Observation, River, RiverDetail } from './types'

// Statiske JSON-filer fra backend/scripts/export_static.py, relativt til der siden ligger
async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${import.meta.env.BASE_URL}api${path}.json`, { cache: 'no-cache' })
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

export const api = {
  meta: () => get<Meta>('/meta'),
  rivers: () => get<River[]>('/rivers'),
  river: (id: string) => get<RiverDetail>(`/rivers/${id}`),
  observed: (id: string, resolution: 'day' | 'hour') => get<Observation[]>(`/rivers/${id}/observed_${resolution}`),
  forecast: (id: string) => get<ForecastDay[]>(`/rivers/${id}/forecast`),
  forecastHourly: (id: string) => get<HourlyForecast[]>(`/rivers/${id}/forecast_hourly`),
}
