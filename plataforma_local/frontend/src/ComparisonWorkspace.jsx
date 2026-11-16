import { MAPA } from './diseno.js'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import { ArrowLeftRight, BarChart3, CalendarDays, Layers3, Map as MapIcon, MapPin, Mountain, Scan, ThermometerSun, X } from 'lucide-react'
import ComparisonPanel from './ComparisonPanel.jsx'
import { CUSCO, getCalendar, getFocos } from './services/api.js'
import { tr } from './i18n.js'

const MAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
const EMPTY = { type: 'FeatureCollection', features: [] }

function geoBounds(geojson) {
  const bounds = new maplibregl.LngLatBounds()
  const visit = (coordinates) => Array.isArray(coordinates?.[0]) ? coordinates.forEach(visit) : bounds.extend(coordinates)
  ;(geojson?.features || []).forEach((feature) => visit(feature.geometry?.coordinates))
  return bounds
}

function boundsGeoJson(bounds) {
  if (!bounds) return EMPTY
  const { west, south, east, north } = bounds
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] } }] }
}

function bboxParam(bounds) {
  return { bbox: [bounds.west, bounds.south, bounds.east, bounds.north].map((number) => number.toFixed(4)).join(',') }
}

function filterByDate(body, period) {
  const features = (body?.features || []).filter((feature) => {
    const date = feature.properties?.fecha_local
    return date && date >= period.from && date <= period.to
  })
  return { ...body, features, n_focos: features.length }
}

function calendarWithExactHotspots(calendar, features) {
  const totals = features.reduce((all, feature) => {
    const key = feature.properties?.fecha_local?.slice(0, 7)
    if (key) all[key] = (all[key] || 0) + (Number(feature.properties?.eq_foco) || 0)
    return all
  }, {})
  return {
    ...calendar,
    celdas: (calendar?.celdas || []).map((cell) => ({
      ...cell,
      focos_armonizados: Number((totals[`${cell.anio}-${String(cell.mes).padStart(2, '0')}`] || 0).toFixed(2)),
    })),
  }
}

function MapPane({ side, region, period, onPeriod, onStats }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const selectingRef = useRef(false)
  const initialRegionRef = useRef(region)
  const [ready, setReady] = useState(false)
  const [focos, setFocos] = useState(EMPTY)
  const initialFocosRef = useRef(focos)
  const [baseMap, setBaseMap] = useState('relief')
  const [layer, setLayer] = useState('surface')
  const [boundary, setBoundary] = useState(true)
  const [selecting, setSelecting] = useState(false)
  const [selection, setSelection] = useState(null)

  useEffect(() => { selectingRef.current = selecting }, [selecting])

  useEffect(() => {
    let active = true
    if (period.from > period.to) { onStats({ loading: false, error: tr('filter.invalid'), total: 0, detections: 0, selection }); return undefined }
    onStats((previous) => ({ ...previous, loading: true, error: '' }))
    const aoi = selection ? bboxParam(selection) : { departamento: CUSCO }
    const apiFrom = period.from.slice(0, 7)
    const apiTo = period.to.slice(0, 7)
    Promise.all([getFocos(aoi, apiFrom, apiTo), getCalendar(aoi, apiFrom, apiTo)])
      .then(([focosResponse, calendarResponse]) => {
        if (!active) return
        const body = filterByDate(focosResponse.body, period)
        setFocos(body)
        const total = (body.features || []).reduce((sum, feature) => sum + (Number(feature.properties?.eq_foco) || 0), 0)
        onStats({ loading: false, error: '', total, detections: body.n_focos ?? body.features?.length ?? 0, selection, calendar: calendarWithExactHotspots(calendarResponse.body, body.features || []) })
      })
      .catch((error) => active && onStats({ loading: false, error: error.message, total: 0, detections: 0, selection, calendar: null }))
    return () => { active = false }
  }, [period, selection, onStats])

  useEffect(() => {
    const map = new maplibregl.Map({ container: containerRef.current, style: MAP_STYLE, center: [-71.97, -13.53], zoom: 6.2, minZoom: 4, maxZoom: 14, attributionControl: false })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    const canvas = map.getCanvas(); const canvasContainer = map.getCanvasContainer()
    let start = null; let box = null
    const point = (event) => { const rect = canvas.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top } }
    const clearBox = () => { box?.remove(); box = null; start = null }
    const down = (event) => {
      if (!selectingRef.current || event.button !== 0) return
      event.preventDefault(); event.stopPropagation(); start = point(event)
      box = document.createElement('div'); box.className = 'fw-selection-box'; canvasContainer.appendChild(box)
      canvas.setPointerCapture?.(event.pointerId)
    }
    const move = (event) => {
      if (!start || !box) return
      event.preventDefault(); const current = point(event)
      box.style.left = `${Math.min(start.x, current.x)}px`; box.style.top = `${Math.min(start.y, current.y)}px`
      box.style.width = `${Math.abs(current.x - start.x)}px`; box.style.height = `${Math.abs(current.y - start.y)}px`
    }
    const up = (event) => {
      if (!start || !box) return
      event.preventDefault(); const end = point(event)
      if (Math.abs(end.x - start.x) > 8 && Math.abs(end.y - start.y) > 8) {
        const first = map.unproject([Math.min(start.x, end.x), Math.max(start.y, end.y)])
        const second = map.unproject([Math.max(start.x, end.x), Math.min(start.y, end.y)])
        setSelection({ west: first.lng, south: first.lat, east: second.lng, north: second.lat })
      }
      clearBox(); setSelecting(false); canvas.releasePointerCapture?.(event.pointerId)
    }
    canvas.addEventListener('pointerdown', down, true); canvas.addEventListener('pointermove', move, true); canvas.addEventListener('pointerup', up, true); canvas.addEventListener('pointercancel', clearBox, true)
    map.on('load', () => {
      map.addSource('imagery', { type: 'raster', tileSize: 256, tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'] })
      map.addSource('reference', { type: 'raster', tileSize: 256, tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'] })
      map.addLayer({ id: 'imagery', type: 'raster', source: 'imagery', paint: { 'raster-saturation': -0.12, 'raster-contrast': 0.08 } })
      map.addLayer({ id: 'reference', type: 'raster', source: 'reference', paint: { 'raster-opacity': 0.82 } })
      map.addSource('region', { type: 'geojson', data: initialRegionRef.current || EMPTY })
      map.addSource('focos', { type: 'geojson', data: initialFocosRef.current })
      map.addSource('selection', { type: 'geojson', data: EMPTY })
      map.addLayer({ id: 'region-fill', type: 'fill', source: 'region', paint: { 'fill-color': MAPA.regionA, 'fill-opacity': 0.04 } })
      map.addLayer({ id: 'region-line', type: 'line', source: 'region', paint: { 'line-color': MAPA.regionB, 'line-width': 2, 'line-dasharray': [2, 1.5] } })
      map.addLayer({ id: 'heat', type: 'heatmap', source: 'focos', maxzoom: 12, paint: { 'heatmap-weight': ['interpolate', ['linear'], ['get', 'eq_foco'], 0, 0.04, 1, 0.75, 3, 1], 'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 5, 0.55, 9, 1.1], 'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(245,158,11,0)', .2, 'rgba(245,158,11,0)', .34, '#fde68a', .52, '#f59e0b', .7, '#ea580c', .86, '#dc2626', 1, '#7f1d1d'], 'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 5, 11, 8, 23, 11, 36], 'heatmap-opacity': .86 } })
      map.addLayer({ id: 'points', type: 'circle', source: 'focos', layout: { visibility: 'none' }, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 2.4, 10, 5.5], 'circle-color': ['match', ['get', 'sensor'], 'MODIS', '#ff9b3f', '#f33932'], 'circle-opacity': .9, 'circle-stroke-color': '#fff', 'circle-stroke-width': .7 } })
      map.addLayer({ id: 'selection-fill', type: 'fill', source: 'selection', paint: { 'fill-color': MAPA.seleccion, 'fill-opacity': .14 } })
      map.addLayer({ id: 'selection-line', type: 'line', source: 'selection', paint: { 'line-color': MAPA.seleccion, 'line-width': 2.5, 'line-dasharray': [2, 1.3] } })
      if (initialRegionRef.current?.features?.length) map.fitBounds(geoBounds(initialRegionRef.current), { padding: 55, duration: 0 })
      setReady(true)
    })
    return () => { canvas.removeEventListener('pointerdown', down, true); canvas.removeEventListener('pointermove', move, true); canvas.removeEventListener('pointerup', up, true); canvas.removeEventListener('pointercancel', clearBox, true); clearBox(); map.remove(); mapRef.current = null }
  }, []) // one independent MapLibre instance per pane

  useEffect(() => { if (ready && mapRef.current?.getSource('focos')) mapRef.current.getSource('focos').setData(focos) }, [focos, ready])
  useEffect(() => { if (ready && region && mapRef.current?.getSource('region')) { mapRef.current.getSource('region').setData(region); mapRef.current.fitBounds(geoBounds(region), { padding: 55, duration: 0 }) } }, [region, ready])
  useEffect(() => { if (ready && mapRef.current?.getSource('selection')) mapRef.current.getSource('selection').setData(boundsGeoJson(selection)) }, [selection, ready])
  useEffect(() => {
    const map = mapRef.current; if (!ready || !map) return
    map.setLayoutProperty('imagery', 'visibility', baseMap === 'relief' ? 'visible' : 'none'); map.setLayoutProperty('reference', 'visibility', baseMap === 'relief' ? 'visible' : 'none')
  }, [baseMap, ready])
  useEffect(() => {
    const map = mapRef.current; if (!ready || !map) return
    map.setLayoutProperty('heat', 'visibility', layer === 'surface' ? 'visible' : 'none'); map.setLayoutProperty('points', 'visibility', layer === 'points' ? 'visible' : 'none')
  }, [layer, ready])
  useEffect(() => { if (ready && mapRef.current) { mapRef.current.setLayoutProperty('region-fill', 'visibility', boundary ? 'visible' : 'none'); mapRef.current.setLayoutProperty('region-line', 'visibility', boundary ? 'visible' : 'none') } }, [boundary, ready])
  useEffect(() => {
    const map = mapRef.current; if (!ready || !map) return
    map.getContainer().classList.toggle('is-selecting', selecting); selecting ? map.dragPan.disable() : map.dragPan.enable()
  }, [selecting, ready])

  return <section className={`fc-split-map is-${side.toLowerCase()}`}>
    <div ref={containerRef} className="fc-split-canvas"/>
    <div className="fc-split-label"><b>{side}</b><span>{tr(`compare.map${side}`)}</span></div>
    <div className="fc-split-dates"><div className="fc-split-date-head"><CalendarDays/><span>{tr('compare.dateRange')}</span></div><label><span>{tr('filter.from')}</span><input type="date" min="2000-11-01" max="2025-12-31" value={period.from} onChange={(event) => onPeriod({ ...period, from: event.target.value })}/></label><label><span>{tr('filter.to')}</span><input type="date" min="2000-11-01" max="2025-12-31" value={period.to} onChange={(event) => onPeriod({ ...period, to: event.target.value })}/></label></div>
    <nav className="fc-split-tools" aria-label={tr('rail.label')}>
      <button className={baseMap === 'relief' ? 'is-active' : ''} title={baseMap === 'relief' ? tr('basemap.standard') : tr('basemap.relief')} onClick={() => setBaseMap((current) => current === 'relief' ? 'standard' : 'relief')}>{baseMap === 'relief' ? <Mountain/> : <MapIcon/>}</button>
      <button className={layer === 'surface' ? 'is-active' : ''} title={layer === 'surface' ? tr('layers.points') : tr('layers.density')} onClick={() => setLayer((current) => current === 'surface' ? 'points' : 'surface')}>{layer === 'surface' ? <ThermometerSun/> : <MapPin/>}</button>
      <button className={boundary ? 'is-active' : ''} title={tr('layers.boundary')} onClick={() => setBoundary((current) => !current)}><Layers3/></button>
      <button className={selecting ? 'is-active' : ''} title={tr('rail.areaTitle')} onClick={() => { setSelection(null); setSelecting((current) => !current) }}><Scan/></button>
      {selection && <button title={tr('sel.clear')} onClick={() => setSelection(null)}><X/></button>}
    </nav>
  </section>
}

export default function ComparisonWorkspace({ calendar, region, regionName, onClose }) {
  const [periodA, setPeriodA] = useState({ from: '2020-01-01', to: '2020-12-31' })
  const [periodB, setPeriodB] = useState({ from: '2025-01-01', to: '2025-12-31' })
  const [statsA, setStatsA] = useState({ loading: true, total: 0 })
  const [statsB, setStatsB] = useState({ loading: true, total: 0 })
  const [compared, setCompared] = useState(false)
  const [details, setDetails] = useState(false)
  const updateA = useMemo(() => (value) => setStatsA(value), [])
  const updateB = useMemo(() => (value) => setStatsB(value), [])
  const invalid = periodA.from > periodA.to || periodB.from > periodB.to
  const difference = statsB.total - statsA.total
  const percent = statsA.total ? difference / statsA.total * 100 : null

  return <div className="fc-compare-workspace">
    <div className="fc-split-stage"><MapPane side="A" region={region} period={periodA} onPeriod={(value) => { setPeriodA(value); setCompared(false) }} onStats={updateA}/><MapPane side="B" region={region} period={periodB} onPeriod={(value) => { setPeriodB(value); setCompared(false) }} onStats={updateB}/></div>
    <button className="fc-workspace-close" onClick={onClose} title={tr('btn.close')}><X size={18}/></button>
    <footer className="fc-compare-actions">
      <div className="fc-compare-side-stat is-a"><span>A · {periodA.from} — {periodA.to}</span><b>{statsA.loading ? '…' : statsA.total.toLocaleString(undefined, { maximumFractionDigits: 1 })}</b></div>
      {compared && !invalid ? <div className="fc-compare-result"><span>{tr('compare.result')}</span><b className={difference >= 0 ? 'is-up' : 'is-down'}>{difference >= 0 ? '+' : '−'}{Math.abs(difference).toLocaleString(undefined, { maximumFractionDigits: 1 })}{percent !== null ? ` · ${percent >= 0 ? '+' : '−'}${Math.abs(percent).toFixed(1)} %` : ''}</b></div> : <div className="fc-compare-prompt">{invalid ? tr('filter.invalid') : tr('compare.ready')}</div>}
      <div className="fc-compare-buttons"><button className="is-primary" disabled={statsA.loading || statsB.loading || invalid} onClick={() => setCompared(true)}><ArrowLeftRight size={15}/>{tr('compare.action')}</button><button disabled={!compared} onClick={() => setDetails(true)}><BarChart3 size={15}/>{tr('compare.details')}</button></div>
      <div className="fc-compare-side-stat is-b"><span>B · {periodB.from} — {periodB.to}</span><b>{statsB.loading ? '…' : statsB.total.toLocaleString(undefined, { maximumFractionDigits: 1 })}</b></div>
    </footer>
    {details && <ComparisonPanel calendar={calendar} calendarA={statsA.calendar} calendarB={statsB.calendar} regionName={regionName} periodA={periodA} periodB={periodB} onClose={() => setDetails(false)}/>} 
  </div>
}
