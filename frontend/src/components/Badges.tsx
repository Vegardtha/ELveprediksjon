import { REGULATION, STATUS } from '../status'
import type { Regulation, Status } from '../types'

export function DamIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2 3h5l2 11H2z" fill="currentColor" />
      <path d="M10 9c1.2-.8 2.4.8 4 0M10 12c1.2-.8 2.4.8 4 0" stroke="currentColor" strokeWidth="1.4" fill="none" />
    </svg>
  )
}

export function RegulationBadge({ regulation, full = false }: { regulation: Regulation; full?: boolean }) {
  if (regulation === 'unregulated' || (!full && regulation !== 'regulated')) return null
  return (
    <span className={`badge reg-${regulation}`} title={REGULATION[regulation].long}>
      {regulation !== 'unknown' && <DamIcon size={12} />}
      {REGULATION[regulation].label}
    </span>
  )
}

export function StatusPill({ status }: { status: Status | null }) {
  if (!status) return <span className="pill">–</span>
  const s = STATUS[status]
  return (
    <span className="pill">
      <span className="dot" style={{ background: s.color }} />
      {s.label}
    </span>
  )
}
