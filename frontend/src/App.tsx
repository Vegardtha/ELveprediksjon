import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { DayPicker } from './components/DayPicker'
import { ListControls } from './components/ListControls'
import { applyFilter, DEFAULT_FILTER } from './filter'
import { RiverDetail } from './components/RiverDetail'
import { RiverList } from './components/RiverList'
import { RiverMap } from './components/RiverMap'
import { SearchBox } from './components/SearchBox'
import { STATUS, STATUS_ORDER, fmtDate, fmtTime, fmtWeekday } from './status'
import type { Meta, River } from './types'

const fromHash = () => decodeURIComponent(location.hash.slice(1)) || null

export default function App() {
  const [rivers, setRivers] = useState<River[]>([])
  const [lines, setLines] = useState<Record<string, [number, number][]>>({})
  const [meta, setMeta] = useState<Meta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(fromHash)
  const [filter, setFilter] = useState(DEFAULT_FILTER)
  // -1 = siste måling, ellers indeks i prognosedagene
  const [day, setDay] = useState(-1)
  const shown = useMemo(() => applyFilter(rivers, filter, day), [rivers, filter, day])

  useEffect(() => {
    Promise.all([api.rivers(), api.meta()])
      .then(([r, m]) => {
        setRivers(r)
        setMeta(m)
      })
      .catch((e) => setError(String(e)))
    // seksjonslinjene er pynt: uten dem tegnes rette streker
    api.sections().then((fc) => setLines(Object.fromEntries(fc.features.map((f) => [f.properties.id, f.geometry.coordinates])))).catch(() => {})
    const onHash = () => setSelected(fromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const select = useCallback((id: string | null) => {
    history.pushState(null, '', id ? `#${id}` : location.pathname)
    setSelected(id)
  }, [])
  const onSelect = useCallback((id: string) => select(id), [select])
  const date = day >= 0 ? rivers.find((r) => r.days.length)?.days[day]?.date : null
  const search = useCallback(
    (q: string) => {
      setFilter((f) => ({ ...f, q }))
      if (q && selected) select(null) // treffene vises i lista
    },
    [selected, select],
  )
  const dayLabel = date ? `${fmtWeekday(date)} ${fmtDate(date)}` : null

  return (
    <div className={`app ${selected ? 'has-detail' : ''}`}>
      <header className="top">
        <h1>
          <svg viewBox="0 0 32 20" aria-hidden="true"><path d="M1 13c5-6 9 4 15-2s10 4 15-2" /><path d="M1 18c5-6 9 4 15-2s10 4 15-2" /></svg>
          Elvepred
        </h1>
        <p>Vannføring og prognoser for padleseksjoner på Østlandet</p>
        <SearchBox value={filter.q} onChange={search} hits={shown.length} />
      </header>
      <section className="map-wrap">
        <RiverMap rivers={shown} lines={lines} day={day} selected={selected} onSelect={onSelect} query={filter.q} />
        <div className="map-days">
          <DayPicker rivers={rivers} day={day} onChange={setDay} />
        </div>
        <div className="map-legend" aria-label="Tegnforklaring">
          {STATUS_ORDER.map((s) => (
            <span key={s}><i className="key-line" style={{ background: STATUS[s].color }} />{STATUS[s].short}</span>
          ))}
          <span><i className="key-line dashed" />Demningsstyrt</span>
        </div>
      </section>
      <section className="side">
        {error && <p className="error">Fant ikke prognosene ({error}). Last siden på nytt om litt.</p>}
        {selected ? (
          <RiverDetail id={selected} onClose={() => select(null)} />
        ) : (
          <>
            <ListControls filter={filter} onChange={setFilter} shown={shown.length} total={rivers.length} dayLabel={dayLabel} />
            <RiverList rivers={shown} selected={selected} onSelect={onSelect} grouped={filter.sort === 'basin'} day={day} />
          </>
        )}
        <footer className="attrib">
          {meta?.run.run_at && <p>Oppdatert {fmtTime(meta.run.run_at)}.</p>}
          <p>
            Prognosene er modellberegninger og kan ta feil, særlig i regulerte elver. Data:{' '}
            {meta?.attribution.map((a, i) => (
              <span key={a.name}>
                {i > 0 && ', '}
                <a href={a.url} target="_blank" rel="noreferrer">{a.name}</a> ({a.what}, {a.license})
              </span>
            ))}
            . Kart © Kartverket.
          </p>
        </footer>
      </section>
    </div>
  )
}
