import { useEffect, useState } from 'react'
import { api } from '../api'
import { REGULATION, STATUS, fmtDate, fmtQ, fmtTime, fmtWeekday, pct } from '../status'
import type { ForecastDay, HourlyForecast, Observation, RiverDetail as Detail } from '../types'
import { DamIcon, RegulationBadge, StatusPill } from './Badges'
import { Gauge } from './Gauge'
import { FlowChart, noon, utc, type FcPoint } from './FlowChart'

interface Data {
  river: Detail
  hourly: Observation[]
  forecast: ForecastDay[]
  hourlyFc: HourlyForecast[]
}

export function RiverDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setData(null)
    Promise.all([api.river(id), api.observed(id, 'hour'), api.forecast(id), api.forecastHourly(id)])
      .then(([river, hourly, forecast, hourlyFc]) => live && setData({ river, hourly, forecast, hourlyFc }))
      .catch((e) => live && setError(String(e)))
    return () => {
      live = false
    }
  }, [id])

  if (error) return <div className="detail"><p className="error">Kunne ikke hente data: {error}</p></div>
  if (!data) return <div className="detail"><p className="muted">Henter prognosen …</p></div>
  const { river: r, hourly, forecast, hourlyFc } = data
  // Timesmodellen de første 48 timene, deretter døgnmodellen for dagene som ligger etter
  const hourEnd = hourlyFc.length ? utc(hourlyFc.at(-1)!.time) : -Infinity
  const laterDays = forecast.filter((f) => noon(f.date) > hourEnd)
  const fcPoints: FcPoint[] = [
    ...hourlyFc.map((f) => ({ t: utc(f.time), kind: 'hour' as const, p10: f.p10, p50: f.p50, p90: f.p90 })),
    ...laterDays.map((f) => ({ t: noon(f.date), kind: 'day' as const, p10: f.p10, p50: f.p50, p90: f.p90 })),
  ]
  const rain = forecast.map((f) => ({ t: noon(f.date), rr: f.rr_forecast }))
  // én rad per 3. time, med nedbør summert over de tre timene
  const hourRows = hourlyFc
    .map((f, i) => ({ ...f, rr3: hourlyFc.slice(Math.max(0, i - 2), i + 1).reduce((a, x) => a + (x.rr ?? 0), 0) }))
    .filter((f) => f.k % 3 === 0)
  const hourLabel = (iso: string) =>
    new Date(utc(iso)).toLocaleString('nb-NO', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  const th = r.thresholds
  const [river, section] = r.name.split(' – ')
  const best = forecast.reduce((a, b) => (b.prob_paddleable > a.prob_paddleable ? b : a), forecast[0])
  const skill = (h: number) => r.skill.find((s) => s.horizon === h)

  return (
    <article className="detail">
      <header className="detail-head">
        <button className="back" onClick={onClose}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" fill="none" stroke="currentColor" strokeWidth="1.8" /></svg>
          Alle seksjoner
        </button>
        <h2>
          {river}
          {section && <span className="section">{section}</span>}
        </h2>
        <div className="sub">
          {r.grade && <span className="grade">Grad {r.grade}</span>}
          <RegulationBadge regulation={r.regulation} full />
          {r.approximate && (
            <span className="badge reg-unknown" title="Målestasjonen står i en nabo-elv eller lenger nede i vassdraget">Omtrentlig måler</span>
          )}
        </div>
      </header>

      <div className="now" style={{ '--c': r.status_now ? STATUS[r.status_now].color : 'var(--line)' } as React.CSSProperties}>
        <div className="now-q">
          <span className="now-num">{fmtQ(r.q_now)}</span> <span className="now-unit">m³/s</span>
        </div>
        <div className="now-text">
          <StatusPill status={r.status_now} />
          <span className="muted">
            {r.station_name ?? r.station}
            {r.q_now_time && `, ${fmtTime(r.q_now_time)}`}
          </span>
        </div>
      </div>
      <Gauge q={r.q_now} th={th} />

      {r.regulation === 'regulated' && (
        <div className="callout">
          <DamIcon size={18} />
          <div>
            <b>{REGULATION.regulated.long}.</b> {r.regulation_note} Prognosen bygger på vær og historikk og kan ikke
            forutse planlagte slipp eller stenging – sjekk siste måling før du drar.
          </div>
        </div>
      )}
      {r.regulation === 'partly' && <p className="note">{r.regulation_note}</p>}

      {best && best.prob_paddleable >= 0.5 ? (
        <p className="headline">
          Beste dag er <b>{fmtWeekday(best.date)} {fmtDate(best.date)}</b> – {pct(best.prob_paddleable)} sjanse for padlbar vannføring.
        </p>
      ) : (
        <p className="headline">Ingen dager med over 50 % sjanse for padlbar vannføring de neste {forecast.length} dagene.</p>
      )}

      <FlowChart hourly={hourly} forecast={fcPoints} rain={rain} thresholds={th} />

      <table className="fc-table">
        <thead>
          <tr>
            <th>Tid</th>
            <th>Status</th>
            <th className="num">Median</th>
            <th className="num">80 %-intervall</th>
            <th className="num">Padlbart</th>
            <th className="num">Nedbør</th>
          </tr>
        </thead>
        <tbody>
          {hourRows.length > 0 && (
            <tr className="group"><td colSpan={6}>Neste 48 timer</td></tr>
          )}
          {hourRows.map((f) => (
            <tr key={f.time}>
              <td>{hourLabel(f.time)}</td>
              <td><span className="dot" style={{ background: STATUS[f.status].color }} /> {STATUS[f.status].short}</td>
              <td className="num">{fmtQ(f.p50)}</td>
              <td className="num muted">{fmtQ(f.p10)}–{fmtQ(f.p90)}</td>
              <td className="num"><b>{pct(f.prob_paddleable)}</b></td>
              <td className="num muted">{f.rr3.toFixed(1)} mm</td>
            </tr>
          ))}
          {laterDays.length > 0 && (
            <tr className="group"><td colSpan={6}>Deretter per døgn (døgnmiddel)</td></tr>
          )}
          {laterDays.map((f) => (
            <tr key={f.date}>
              <td>{fmtWeekday(f.date)} {fmtDate(f.date)}</td>
              <td><span className="dot" style={{ background: STATUS[f.status].color }} /> {STATUS[f.status].short}</td>
              <td className="num">{fmtQ(f.p50)}</td>
              <td className="num muted">{fmtQ(f.p10)}–{fmtQ(f.p90)}</td>
              <td className="num"><b>{pct(f.prob_paddleable)}</b></td>
              <td className="num muted">{f.rr_forecast == null ? '–' : `${f.rr_forecast.toFixed(1)} mm`}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <dl className="facts">
        <div><dt>Padlbart</dt><dd>{fmtQ(th.minimum)}–{fmtQ(th.maximum)} m³/s</dd></div>
        <div><dt>Optimalt</dt><dd>{fmtQ(th.optimum)}–{fmtQ(th.maximum)} m³/s</dd></div>
        <div><dt>For mye</dt><dd>over {fmtQ(th.impossible)} m³/s</dd></div>
        <div>
          <dt>Nivåer fra</dt>
          <dd>
            {r.nokken_url ? <a href={r.nokken_url} target="_blank" rel="noreferrer">{th.source}</a> : th.source}
            {r.approximate && ' (omtrentlig)'}
          </dd>
        </div>
        {skill(1) && skill(3) && skill(7) && (
          <div className="wide">
            <dt>Treffsikkerhet dager (NSE, testperiode)</dt>
            <dd>dag 1: {skill(1)!.NSE.toFixed(2)} · dag 3: {skill(3)!.NSE.toFixed(2)} · dag 7: {skill(7)!.NSE.toFixed(2)}</dd>
          </div>
        )}
        {r.skill_hourly.length > 0 && (
          <div className="wide">
            <dt>Treffsikkerhet timer (NSE, testperiode)</dt>
            <dd>
              {r.skill_hourly.filter((x) => [6, 24, 48].includes(x.hours)).map((x) => `${x.hours} t: ${x.NSE.toFixed(2)}`).join(' · ')}
            </dd>
          </div>
        )}
      </dl>
    </article>
  )
}
