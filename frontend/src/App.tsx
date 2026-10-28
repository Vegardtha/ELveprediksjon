import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { DamIcon } from './components/Badges'
import { ListControls } from './components/ListControls'
import { applyFilter, DEFAULT_FILTER } from './filter'
import { RiverDetail } from './components/RiverDetail'
import { RiverList } from './components/RiverList'
import { RiverMap } from './components/RiverMap'
import { STATUS, STATUS_ORDER, fmtTime } from './status'
import type { Meta, River } from './types'

const fromHash = () => decodeURIComponent(location.hash.slice(1)) || null

export default function App() {
  const [rivers, setRivers] = useState<River[]>([])
  const [meta, setMeta] = useState<Meta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(fromHash)
  const [filter, setFilter] = useState(DEFAULT_FILTER)
  const shown = useMemo(() => applyFilter(rivers, filter), [rivers, filter])

  useEffect(() => {
    Promise.all([api.rivers(), api.meta()])
      .then(([r, m]) => {
        setRivers(r)
        setMeta(m)
      })
      .catch((e) => setError(String(e)))
    const onHash = () => setSelected(fromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const select = useCallback((id: string | null) => {
    history.pushState(null, '', id ? `#${id}` : location.pathname)
    setSelected(id)
  }, [])
  const onSelect = useCallback((id: string) => select(id), [select])

  return (
    <div className={`app ${selected ? 'has-detail' : ''}`}>
      <header className="top">
        <h1>Elvepred</h1>
        <span className="muted">Vannføringsprognoser for padleelver på Østlandet</span>
      </header>
      <section className="map-wrap">
        <RiverMap rivers={shown} selected={selected} onSelect={onSelect} />
        <div className="map-legend">
          {STATUS_ORDER.map((s) => (
            <span key={s}><i className="dot" style={{ background: STATUS[s].color }} />{STATUS[s].short}</span>
          ))}
          <span><i className="marker-key"><DamIcon size={10} /></i>Demningsstyrt</span>
        </div>
      </section>
      <section className="side">
        {error && <p className="error">Kunne ikke hente data: {error}</p>}
        {selected ? (
          <RiverDetail id={selected} onClose={() => select(null)} />
        ) : (
          <>
            <ListControls filter={filter} onChange={setFilter} shown={shown.length} total={rivers.length} />
            <div className="list-head">
              <span>Elv · nå</span>
              <span className="muted">Neste dager · % sjanse for padlbart</span>
            </div>
            <RiverList rivers={shown} selected={selected} onSelect={onSelect} grouped={filter.sort === 'basin'} />
          </>
        )}
        <footer className="attrib">
          {meta?.run.run_at && <p>Oppdatert {fmtTime(meta.run.run_at)}.</p>}
          <p>
            Prognosene er modellberegninger og kan ta feil – særlig i regulerte elver. Data:{' '}
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
