interface Props {
  value: string
  onChange: (q: string) => void
  hits: number
}

/** Søk etter elv, seksjon, målestasjon eller vassdrag. Filtrerer lista og kartet, og kartet zoomer inn på treffene. */
export function SearchBox({ value, onChange, hits }: Props) {
  return (
    <div className="search" role="search">
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="m11 11 3.5 3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <input
        type="search"
        placeholder="Søk etter elv, seksjon eller sted"
        aria-label="Søk etter elv, seksjon eller sted"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onChange('')}
      />
      {value && <span className="search-hits" aria-live="polite">{hits === 0 ? 'Ingen treff' : `${hits} treff`}</span>}
    </div>
  )
}
