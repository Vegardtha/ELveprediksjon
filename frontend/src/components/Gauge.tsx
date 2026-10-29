import { STATUS, fmtQ } from '../status'
import type { Thresholds } from '../types'

/** Vannføringen nå mot seksjonens nivåer, på logaritmisk skala som en vannstandsmåler. */
export function Gauge({ q, th }: { q: number | null; th: Thresholds }) {
  const lo = Math.max(0.1, th.minimum * 0.4)
  const hi = th.impossible * 1.6
  const x = (v: number) => `${(100 * Math.log(Math.min(Math.max(v, lo), hi) / lo)) / Math.log(hi / lo)}%`
  const zones = [
    { from: lo, to: th.minimum, c: STATUS.low.color },
    { from: th.minimum, to: th.optimum, c: STATUS['min-opt'].color },
    { from: th.optimum, to: th.maximum, c: STATUS['opt-max'].color },
    { from: th.maximum, to: th.impossible, c: STATUS.high.color },
    { from: th.impossible, to: hi, c: STATUS.impossible.color },
  ].filter((z) => z.to > z.from)
  const ticks = [...new Set([th.minimum, th.optimum, th.maximum, th.impossible])]

  return (
    <div className="gauge" role="img" aria-label={`Nå ${fmtQ(q)} m³/s. Padlbart ${fmtQ(th.minimum)} til ${fmtQ(th.maximum)}, optimalt fra ${fmtQ(th.optimum)}, for mye over ${fmtQ(th.impossible)}.`}>
      <div className="gauge-track">
        {zones.map((z) => (
          <span key={z.from} style={{ left: x(z.from), width: `calc(${x(z.to)} - ${x(z.from)})`, background: z.c }} />
        ))}
        {q != null && <b className="gauge-now" style={{ left: x(q) }} />}
      </div>
      <div className="gauge-ticks" aria-hidden="true">
        {ticks.map((t) => <span key={t} style={{ left: x(t) }}>{fmtQ(t)}</span>)}
      </div>
    </div>
  )
}
