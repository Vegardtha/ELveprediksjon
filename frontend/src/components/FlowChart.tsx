import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { STATUS, fmtQ } from '../status'
import type { Observation, Thresholds } from '../types'

/** Prognosepunkt med tidspunkt i ms. `day` = døgnmiddel (plottes midt på dagen), `hour` = timesverdi. */
export interface FcPoint {
  t: number
  kind: 'hour' | 'day'
  p10: number
  p50: number
  p90: number
}

interface Props {
  hourly: Observation[]
  forecast: FcPoint[]
  rain: { t: number; rr: number | null }[]
  thresholds: Thresholds
}

interface Point {
  t: number
  hour?: number
  p50?: number
  band?: [number, number]
  kind?: 'hour' | 'day' | 'bridge'
}

const HOUR = 3_600_000
const DAY = 24 * HOUR
const HISTORY_HOURS = 48
// Døgnverdier plottes midt på dagen; timeverdier fra HydAPI er i UTC
export const noon = (iso: string) => new Date(iso.slice(0, 10) + 'T12:00:00').getTime()
export const utc = (iso: string) => new Date(/[Z+]/.test(iso.slice(10)) ? iso : iso + 'Z').getTime()

const OBS = 'var(--series-obs)'
const FC = 'var(--series-fc)'

function buildData({ hourly, forecast }: Props): Point[] {
  const last = hourly.at(-1)
  const from = last ? utc(last.time) - HISTORY_HOURS * HOUR : 0
  const pts: Point[] = hourly.map((o) => ({ t: utc(o.time), hour: o.q })).filter((p) => p.t >= from)
  // knytt prognosen til siste timesmåling så linjen og båndet ikke henger i luften
  if (last) pts.push({ t: utc(last.time), p50: last.q, band: [last.q, last.q], kind: 'bridge' })
  pts.push(...forecast.map((f) => ({ t: f.t, p50: f.p50, band: [f.p10, f.p90] as [number, number], kind: f.kind })))
  return pts.sort((a, b) => a.t - b.t)
}

const fmtWhen = (t: number, withHour: boolean) =>
  new Date(t).toLocaleString('nb-NO', {
    weekday: 'short', day: 'numeric', month: 'short', ...(withHour ? { hour: '2-digit', minute: '2-digit' } : {}),
  })

function Tip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const isFc = p.kind === 'hour' || p.kind === 'day'
  return (
    <div className="tip">
      <div className="tip-h">{fmtWhen(p.t, p.hour != null || p.kind === 'hour')}</div>
      {p.hour != null && <div>Målt: <b>{fmtQ(p.hour)}</b> m³/s</div>}
      {isFc && p.band && (
        <>
          <div>Prognose{p.kind === 'day' ? ' (døgnmiddel)' : ''}: <b>{fmtQ(p.p50)}</b> m³/s</div>
          <div className="muted">80 % intervall: {fmtQ(p.band[0])}–{fmtQ(p.band[1])}</div>
        </>
      )}
    </div>
  )
}

// Punkter bare på døgnverdiene, så overgangen fra time til døgn synes
function DayDot(props: { cx?: number; cy?: number; payload?: Point; index?: number }) {
  const { cx, cy, payload, index } = props
  if (payload?.kind !== 'day' || cx == null || cy == null) return <g key={index} />
  return <circle key={index} cx={cx} cy={cy} r={3} fill={FC} />
}

export function FlowChart(props: Props) {
  const { thresholds: th, forecast, rain } = props
  const data = buildData(props)
  if (!data.length) return null
  const t0 = data[0].t - HOUR
  const t1 = data.at(-1)!.t + DAY / 2
  const dataMax = Math.max(...data.flatMap((p) => [p.hour ?? 0, p.band?.[1] ?? 0]))
  const yMax = Math.ceil(Math.max(dataMax * 1.08, th.maximum * 1.15))
  const now = Date.now()
  const hourEnd = Math.max(...forecast.filter((f) => f.kind === 'hour').map((f) => f.t))

  // midnatt hver dag, i lokal tid så sommertidsskifte ikke forskyver etikettene
  const ticks: number[] = []
  for (const d = new Date(t0); d.getTime() <= t1; d.setDate(d.getDate() + 1)) {
    d.setHours(0, 0, 0, 0)
    if (d.getTime() >= t0) ticks.push(d.getTime())
  }
  const xAxis = {
    dataKey: 't',
    type: 'number' as const,
    domain: [t0, t1],
    scale: 'time' as const,
    ticks,
    tickFormatter: (t: number) => new Date(t).toLocaleDateString('nb-NO', { day: 'numeric', month: 'numeric' }),
    tick: { fill: 'var(--ink-2)', fontSize: 12 },
    stroke: 'var(--axis)',
  }
  const zone = (y1: number, y2: number, color: string) => (
    <ReferenceArea y1={y1} y2={Math.min(y2, yMax)} fill={color} fillOpacity={0.12} stroke="none" ifOverflow="hidden" />
  )
  const line = (y: number, label: string) =>
    y <= yMax && (
      <ReferenceLine
        y={y}
        stroke="var(--axis)"
        strokeDasharray="2 4"
        label={{ value: `${label} ${fmtQ(y)}`, position: 'insideTopLeft', fill: 'var(--ink-2)', fontSize: 11 }}
      />
    )

  return (
    <div className="chart">
      <div className="legend">
        <span><i className="sw line" style={{ background: OBS }} />Målt siste 48 t</span>
        {forecast.length > 0 && (
          <>
            <span><i className="sw line dashed" style={{ borderColor: FC }} />Prognose (median)</span>
            <span><i className="sw band" style={{ background: FC }} />80 % usikkerhet</span>
          </>
        )}
        <span><i className="sw band" style={{ background: STATUS['opt-max'].color }} />Optimalt</span>
        <span><i className="sw band" style={{ background: STATUS['min-opt'].color }} />Padlbart</span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 14, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          {zone(th.minimum, th.optimum, STATUS['min-opt'].color)}
          {zone(th.optimum, th.maximum, STATUS['opt-max'].color)}
          {zone(th.maximum, th.impossible, STATUS.high.color)}
          {th.impossible < yMax && zone(th.impossible, yMax, STATUS.impossible.color)}
          {line(th.minimum, 'min')}
          {th.optimum !== th.minimum && line(th.optimum, 'opt')}
          {line(th.maximum, 'maks')}
          <XAxis {...xAxis} />
          <YAxis domain={[0, yMax]} tick={{ fill: 'var(--ink-2)', fontSize: 12 }} stroke="var(--axis)" width={48} />
          <ReferenceLine x={now} stroke="var(--ink-2)" label={{ value: 'nå', position: 'top', fill: 'var(--ink-2)', fontSize: 11 }} />
          {isFinite(hourEnd) && (
            <ReferenceLine x={hourEnd} stroke="var(--axis)" strokeDasharray="3 3"
              label={{ value: '48 t', position: 'top', fill: 'var(--ink-2)', fontSize: 11 }} />
          )}
          <Area dataKey="band" stroke="none" fill={FC} fillOpacity={0.2} connectNulls isAnimationActive={false} />
          <Line dataKey="hour" stroke={OBS} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
          <Line dataKey="p50" stroke={FC} strokeWidth={2} strokeDasharray="5 4" dot={<DayDot />} connectNulls isAnimationActive={false} />
          <Tooltip content={<Tip />} cursor={{ stroke: 'var(--axis)' }} />
        </ComposedChart>
      </ResponsiveContainer>
      {rain.length > 0 && (
        <>
          <div className="chart-sub">Varslet nedbør i feltet (mm/døgn)</div>
          <ResponsiveContainer width="100%" height={70}>
            <BarChart data={rain} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
              <XAxis {...xAxis} hide />
              <YAxis tick={{ fill: 'var(--ink-2)', fontSize: 11 }} stroke="var(--axis)" width={48} />
              <Bar dataKey="rr" fill="var(--series-rain)" radius={[2, 2, 0, 0]} barSize={8} isAnimationActive={false} />
              <Tooltip
                cursor={{ fill: 'var(--grid)' }}
                content={({ active, payload }) =>
                  active && payload?.length ? (
                    <div className="tip">{fmtWhen(payload[0].payload.t, false)}: {Number(payload[0].value).toFixed(1)} mm</div>
                  ) : null
                }
              />
            </BarChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  )
}
