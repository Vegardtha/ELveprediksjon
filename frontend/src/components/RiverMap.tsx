import maplibregl from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { STATUS, fmtQ, pct, statusOn } from '../status'
import type { River } from '../types'

interface Props {
  rivers: River[]
  lines: Record<string, [number, number][]>
  day: number
  selected: string | null
  onSelect: (id: string) => void
}

const dark = () => matchMedia('(prefers-color-scheme: dark)').matches

// Kartverkets gråtonekart (CC BY 4.0): fargene på kartet er da bare vannføringen. Navn med glyfer fra MapLibre.
const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  sources: {
    topo: {
      type: 'raster',
      tiles: ['https://cache.kartverket.no/v1/wmts/1.0.0/topograatone/default/webmercator/{z}/{y}/{x}.png'],
      tileSize: 256,
      attribution: '© <a href="https://www.kartverket.no">Kartverket</a> · elvenett © <a href="https://www.nve.no">NVE</a>',
      maxzoom: 18,
    },
  },
  layers: [{ id: 'topo', type: 'raster', source: 'topo', paint: dark()
    ? { 'raster-brightness-min': 0.24, 'raster-brightness-max': 0.4, 'raster-saturation': -0.5 }
    : { 'raster-brightness-min': 0.08, 'raster-contrast': -0.1 } }],
}

const lngLat = (p: [number, number]): [number, number] => [p[1], p[0]]
const start = (r: River) => lngLat(r.putin ?? r.station_pos)

/** Linje langs elva når den finnes, ellers rett strek fra innsett til utsett. */
function geometry(r: River, lines: Props['lines']): [number, number][] | null {
  if (lines[r.id]) return lines[r.id]
  return r.putin && r.takeout ? [lngLat(r.putin), lngLat(r.takeout)] : null
}

function features(rivers: River[], lines: Props['lines'], day: number) {
  const props = (r: River) => {
    const s = statusOn(r, day)
    return {
      id: r.id,
      name: r.name,
      color: s ? STATUS[s].color : '#888',
      rank: s ? STATUS[s].rank : 0,
      regulated: r.regulation === 'regulated',
    }
  }
  const sections: GeoJSON.Feature[] = []
  const starts: GeoJSON.Feature[] = []
  for (const r of rivers) {
    const g = geometry(r, lines)
    if (g) sections.push({ type: 'Feature', properties: props(r), geometry: { type: 'LineString', coordinates: g } })
    starts.push({ type: 'Feature', properties: props(r), geometry: { type: 'Point', coordinates: g ? g[0] : start(r) } })
  }
  return {
    sections: { type: 'FeatureCollection', features: sections } as GeoJSON.FeatureCollection,
    starts: { type: 'FeatureCollection', features: starts } as GeoJSON.FeatureCollection,
  }
}

const width = (base: number): maplibregl.ExpressionSpecification =>
  ['interpolate', ['exponential', 1.6], ['zoom'], 6, base * 0.7, 9, base, 13, base * 2.6]

function addLayers(m: maplibregl.Map) {
  const empty: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
  m.addSource('sections', { type: 'geojson', data: empty })
  m.addSource('starts', { type: 'geojson', data: empty })
  const halo = dark() ? '#0c171d' : '#ffffff'
  // valgt seksjon får en bred halo under alt annet
  m.addLayer({ id: 'sel-halo', type: 'line', source: 'sections', filter: ['==', ['get', 'id'], ''],
    paint: { 'line-color': dark() ? '#e6eef1' : '#102029', 'line-width': width(11), 'line-opacity': 0.9 },
    layout: { 'line-cap': 'round', 'line-join': 'round' } })
  m.addLayer({ id: 'casing', type: 'line', source: 'sections',
    paint: { 'line-color': halo, 'line-width': width(6.5) },
    layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'rank'] } })
  m.addLayer({ id: 'line', type: 'line', source: 'sections', filter: ['!', ['get', 'regulated']],
    paint: { 'line-color': ['get', 'color'], 'line-width': width(4) },
    layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'rank'] } })
  // demningsstyrte seksjoner stiples
  m.addLayer({ id: 'line-reg', type: 'line', source: 'sections', filter: ['get', 'regulated'],
    paint: { 'line-color': ['get', 'color'], 'line-width': width(4), 'line-dasharray': [1.2, 0.9] },
    layout: { 'line-join': 'round', 'line-sort-key': ['get', 'rank'] } })
  m.addLayer({ id: 'start', type: 'circle', source: 'starts',
    paint: {
      'circle-color': ['get', 'color'],
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 4.5, 10, 6, 13, 7],
      'circle-stroke-color': halo,
      'circle-stroke-width': 2,
    },
    layout: { 'circle-sort-key': ['get', 'rank'] } })
  m.addLayer({ id: 'label', type: 'symbol', source: 'starts', minzoom: 8.5,
    layout: {
      'text-field': ['get', 'name'],
      'text-font': ['Open Sans Semibold'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 8.5, 11, 12, 13],
      'text-anchor': 'left',
      'text-offset': [0.8, 0],
      'text-optional': true,
      'symbol-sort-key': ['-', 10, ['get', 'rank']],
    },
    paint: {
      'text-color': dark() ? '#e6eef1' : '#102029',
      'text-halo-color': halo,
      'text-halo-width': 1.6,
    } })
}

const HIT = ['line', 'line-reg', 'start']

export function RiverMap({ rivers, lines, day, selected, onSelect }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const fitted = useRef(false)
  const byId = useRef(new Map<string, River>())
  byId.current = new Map(rivers.map((r) => [r.id, r]))
  const dayRef = useRef(day)
  dayRef.current = day
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect

  useEffect(() => {
    const m = new maplibregl.Map({ container: el.current!, style: STYLE, center: [10.2, 60.6], zoom: 6.6, attributionControl: { compact: true } })
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.current = m
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'map-tip' })
    // kildehenvisningen foldes sammen etter første tegning så den ikke dekker tegnforklaringen
    m.once('idle', () => el.current?.querySelector('.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show'))
    m.on('load', () => {
      addLayers(m)
      setReady(true)
    })
    for (const layer of HIT) {
      m.on('mousemove', layer, (e) => {
        const r = byId.current.get(e.features?.[0]?.properties.id)
        if (!r) return
        m.getCanvas().style.cursor = 'pointer'
        const s = statusOn(r, dayRef.current)
        const d = dayRef.current >= 0 ? r.days[dayRef.current] : null
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<b>${r.name}</b>${r.grade ? ` <span>${r.grade}</span>` : ''}<br>` +
              `<i style="background:${s ? STATUS[s].color : '#888'}"></i>${s ? STATUS[s].label : 'Ukjent'} · ` +
              (d ? `${fmtQ(d.p50)} m³/s, ${pct(d.prob_paddleable)} sjanse` : `${fmtQ(r.q_now)} m³/s`),
          )
          .addTo(m)
      })
      m.on('mouseleave', layer, () => {
        m.getCanvas().style.cursor = ''
        popup.remove()
      })
      m.on('click', layer, (e) => {
        const id = e.features?.[0]?.properties.id
        if (id) selectRef.current(id)
      })
    }
    // grid-raden endrer høyde når detaljpanelet åpnes; MapLibre fanger ikke alltid det opp selv
    const ro = new ResizeObserver(() => m.resize())
    ro.observe(el.current!)
    return () => {
      ro.disconnect()
      m.remove()
    }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m || !ready || !rivers.length) return
    const { sections, starts } = features(rivers, lines, day)
    ;(m.getSource('sections') as maplibregl.GeoJSONSource).setData(sections)
    ;(m.getSource('starts') as maplibregl.GeoJSONSource).setData(starts)
    if (!fitted.current && !selected) {
      m.resize() // kartet kan ha fått sin endelige størrelse etter at det ble laget
      const b = new maplibregl.LngLatBounds()
      rivers.forEach((r) => (geometry(r, lines) ?? [start(r)]).forEach((p) => b.extend(p)))
      m.fitBounds(b, { padding: { top: 90, bottom: 40, left: 30, right: 30 }, maxZoom: 9, duration: 0 })
      fitted.current = true
    }
  }, [ready, rivers, lines, day, selected])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    m.setFilter('sel-halo', ['==', ['get', 'id'], selected ?? ''])
    const r = rivers.find((x) => x.id === selected)
    if (!r) return
    fitted.current = true
    const g = geometry(r, lines)
    if (g && g.length > 1) {
      const b = new maplibregl.LngLatBounds()
      g.forEach((p) => b.extend(p))
      m.fitBounds(b, { padding: 70, maxZoom: 12.5, duration: 700 })
    } else m.easeTo({ center: start(r), zoom: Math.max(m.getZoom(), 11), duration: 700 })
  }, [ready, selected, rivers, lines])

  return <div ref={el} className="map" role="region" aria-label="Kart over seksjonene, farget etter vannføring" />
}
