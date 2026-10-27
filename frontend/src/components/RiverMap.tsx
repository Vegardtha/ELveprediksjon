import maplibregl from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import { REGULATION, STATUS, fmtQ } from '../status'
import type { River } from '../types'

interface Props {
  rivers: River[]
  selected: string | null
  onSelect: (id: string) => void
}

// Kartverkets topografiske kart (CC BY 4.0)
const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    topo: {
      type: 'raster',
      tiles: ['https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png'],
      tileSize: 256,
      attribution: '© <a href="https://www.kartverket.no">Kartverket</a>',
      maxzoom: 18,
    },
  },
  layers: [{ id: 'topo', type: 'raster', source: 'topo' }],
}

const pos = (r: River): [number, number] => {
  const p = r.putin ?? r.station_pos
  return [p[1], p[0]]
}

function lines(rivers: River[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: rivers
      .filter((r) => r.putin && r.takeout)
      .map((r) => ({
        type: 'Feature',
        properties: { id: r.id, color: r.status_now ? STATUS[r.status_now].color : '#888' },
        geometry: { type: 'LineString', coordinates: [pos(r), [r.takeout![1], r.takeout![0]]] },
      })),
  }
}

export function RiverMap({ rivers, selected, onSelect }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<Map<string, HTMLElement>>(new Map())

  useEffect(() => {
    const m = new maplibregl.Map({ container: el.current!, style: STYLE, center: [10.3, 60.0], zoom: 7.3 })
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.current = m
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
    if (!m || !rivers.length) return
    const addLines = () => {
      const data = lines(rivers)
      const src = m.getSource('sections') as maplibregl.GeoJSONSource | undefined
      if (src) return src.setData(data)
      m.addSource('sections', { type: 'geojson', data })
      m.addLayer({ id: 'sections-casing', type: 'line', source: 'sections', paint: { 'line-color': '#fff', 'line-width': 7 }, layout: { 'line-cap': 'round' } })
      m.addLayer({ id: 'sections', type: 'line', source: 'sections', paint: { 'line-color': ['get', 'color'], 'line-width': 4 }, layout: { 'line-cap': 'round' } })
    }
    if (m.isStyleLoaded()) addLines()
    else m.once('load', addLines)

    const added: maplibregl.Marker[] = []
    markers.current.clear()
    for (const r of rivers) {
      const node = document.createElement('button')
      const regulated = r.regulation === 'regulated'
      node.className = `marker ${regulated ? 'regulated' : ''}`
      node.style.setProperty('--c', r.status_now ? STATUS[r.status_now].color : '#888')
      node.setAttribute(
        'aria-label',
        `${r.name}: ${r.status_now ? STATUS[r.status_now].label : 'ukjent'}, ${fmtQ(r.q_now)} m³/s${regulated ? `. ${REGULATION.regulated.label}` : ''}`,
      )
      node.innerHTML = `<span class="marker-dot"></span><span class="marker-label">${r.name}</span>`
      node.addEventListener('click', (e) => {
        e.stopPropagation()
        onSelect(r.id)
      })
      markers.current.set(r.id, node)
      added.push(new maplibregl.Marker({ element: node, anchor: 'left', offset: [-9, 0] }).setLngLat(pos(r)).addTo(m))
    }
    return () => added.forEach((mk) => mk.remove())
  }, [rivers, onSelect])

  useEffect(() => {
    markers.current.forEach((node, id) => node.classList.toggle('selected', id === selected))
    const r = rivers.find((x) => x.id === selected)
    if (r && map.current) map.current.easeTo({ center: pos(r), zoom: Math.max(map.current.getZoom(), 9), duration: 600 })
  }, [selected, rivers])

  return <div ref={el} className="map" />
}
