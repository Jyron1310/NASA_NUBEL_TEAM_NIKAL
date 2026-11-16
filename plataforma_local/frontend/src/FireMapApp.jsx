// Nikal Cusco: interfaz de Dante (rama `dante`, "Firewatch Perú") adaptada a la plataforma.
// Cambios respecto al original: datos reales de Cusco desde nuestra API (sin datos demo ni FIRMS
// en vivo), solo Cusco, unidad "focos armonizados", sin FRP, y la línea de tiempo de 5 días pasa a
// ser el calendario histórico mes x año del PLAN (2000-11 a 2025-12).
import { createElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import {
  ArrowLeftRight, CalendarDays, ChevronLeft, ChevronRight, CircleHelp, Database, Download, FileText, Flame, Gauge, Landmark,
  Layers3, Map as MapIcon, MapPin, MessageCircleQuestion, Mountain, Pause, Play, Radio, Satellite, Scan, ShieldAlert,
  SlidersHorizontal,
  ThermometerSun, Trash2, X,
} from 'lucide-react'
import AmbitosPanel from './AmbitosPanel.jsx'
import SimplePanel from './SimplePanel.jsx'
import PanelHistoria from './PanelHistoria.jsx'
import { ChapterRail, SeasonRibbon } from './Narrativa.jsx'
import { MAPA, NK } from './diseno.js'
import NikalSnake from './NikalSnake.jsx'
import TutorialGuide from './TutorialGuide.jsx'
import IntroWelcome from './IntroWelcome.jsx'
import { IcoFocos, IcoHabitual, IcoHistorico, IcoPlano, IcoPxArea, IcoPxCalendario, IcoPxCapas, IcoPxComparar, IcoPxHerramientas, IcoRelieve, IcoSatelite, IcoVivo } from './NkIcons.jsx'
import PeligroFiltro from './PeligroFiltro.jsx'
import { clasificar, prepararUnidades } from './peligro.js'
import ComparisonWorkspace from './ComparisonWorkspace.jsx'
import { LANGS, getLang, locale, months, setLang, tr } from './i18n.js'
import { CUSCO, downloadCsv, getAmbitoGeojson, getCalendar, getDepartments, getFocos, getMonth, getTiempoReal, informeUrl } from './services/api.js'

// Informe técnico (HTML imprimible) en una pestaña nueva (Antonio, PR #14).
const openReport = (url) => window.open(url, '_blank', 'noopener')

maplibregl.setWorkerUrl(maplibreWorkerUrl)

const MAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
const SATELLITE_STYLE = {
  version: 8,
  sources: {
    imagery: {
      type: 'raster',
      tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      attribution: 'Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community',
    },
  },
  layers: [{ id: 'satellite-imagery', type: 'raster', source: 'imagery', paint: { 'raster-saturation': 0.08, 'raster-contrast': 0.08 } }],
}
const EMPTY = { type: 'FeatureCollection', features: [] }
// Íconos: propios de Nikal (NkIcons.jsx) o los de Dante con ?diseno=dante.
const I = NK
  ? { focos: IcoFocos, calendario: IcoPxCalendario, area: IcoPxArea, ajustes: IcoPxCapas, capas: IcoPxHerramientas, historico: IcoHistorico, vivo: IcoVivo, plano: IcoPlano, relieve: IcoRelieve, habitual: IcoHabitual, satelite: IcoSatelite }
  : { focos: Flame, calendario: CalendarDays, area: Scan, ajustes: SlidersHorizontal, capas: Layers3, historico: CalendarDays, vivo: Radio, plano: MapIcon, relieve: Mountain, habitual: Gauge, satelite: Satellite }
const FIRST_YEAR = 2000
const LAST_YEAR = 2025
// El aviso del tutorial sale cada vez que se entra al mapa desde la bienvenida (?tutorialPrompt=1).
// El parámetro se quita de la URL al leerlo: al recargar el mapa ya no vuelve a salir.
const AVISO_TUTORIAL = (() => {
  const q = new URLSearchParams(window.location.search)
  if (q.get('tutorialPrompt') !== '1') return false
  q.delete('tutorialPrompt')
  try { window.history.replaceState(null, '', `${window.location.pathname}?${q.toString()}${window.location.hash}`) } catch { /* sin history */ }
  return true
})()
const YEARS = Array.from({ length: LAST_YEAR - FIRST_YEAR + 1 }, (_, i) => FIRST_YEAR + i)
// YlOrRd (ColorBrewer, apta para daltonismo) para los tramos con fuego; el 0 va en gris neutro.
const YLORRD = ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026']
const ZERO = '#e4e7ec'               // 0 focos: gris claro (no debe resaltar)
const calidadLabel = (q) => tr(`calidad.${q}`)
const catLabel = (c) => (c ? tr(`cat.${c}`) : tr('noData'))
const CATEGORIA = {
  'muy por debajo': 'bajo', 'por debajo': 'bajo', normal: 'moderado',
  'por encima': 'alto', 'muy por encima': 'alto', incierta: 'incierto',
}
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? '–'
  : Number(v).toLocaleString(locale(), { minimumFractionDigits: d, maximumFractionDigits: d })
const fmtFocos = (v) => (v > 0 && v < 1 ? fmt(v, 1) : fmt(v))
const ym = (y, m) => `${y}-${String(m).padStart(2, '0')}`
const monthStart = (y, m) => `${ym(y, m)}-01`
const monthEnd = (y, m) => `${ym(y, m)}-${String(new Date(y, m, 0).getDate()).padStart(2, '0')}`
const filterFocosByDate = (body, from, to) => {
  if (!from || !to) return body
  const features = (body?.features || []).filter((feature) => {
    const date = feature.properties?.fecha_local
    return date && date >= from && date <= to
  })
  return { ...body, features, n_focos: features.length }
}

function classColor(value, breaks) {
  if (!value) return ZERO
  let i = 0
  while (i < breaks.length && value > breaks[i]) i++
  return YLORRD[Math.min(i, YLORRD.length - 1)]
}

// Anomalía: azul (por debajo) - blanco - rojo (por encima), de -2 a +2 (apta para daltonismo).
const DIVERGING = [[-2, '#2166ac'], [-1, '#67a9cf'], [0, '#f7f7f7'], [1, '#ef8a62'], [2, '#b2182b']]
function mixHex(a, b, t) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16)
  const ch = (s) => Math.round(((pa >> s) & 255) + (((pb >> s) & 255) - ((pa >> s) & 255)) * t)
  return `#${[16, 8, 0].map((s) => ch(s).toString(16).padStart(2, '0')).join('')}`
}
function divergingColor(v) {
  if (v <= DIVERGING[0][0]) return DIVERGING[0][1]
  for (let i = 1; i < DIVERGING.length; i++) {
    const [x1, c1] = DIVERGING[i], [x0, c0] = DIVERGING[i - 1]
    if (v <= x1) return mixHex(c0, c1, (v - x0) / (x1 - x0))
  }
  return DIVERGING[DIVERGING.length - 1][1]
}

// Texto oscuro sobre colores claros (amarillos) y claro sobre oscuros.
function inkFor(color) {
  if (!color.startsWith('#')) return '#f7fbf8'
  const n = parseInt(color.slice(1), 16)
  const lum = 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)
  return lum > 150 ? '#1d2330' : '#f7fbf8'
}

function boundsOf(geojson) {
  const coords = geojson.features.flatMap((f) => (f.geometry.type === 'MultiPolygon'
    ? f.geometry.coordinates.flatMap((p) => p[0]) : f.geometry.coordinates[0]))
  return coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]))
}

// Máscara: oscurece todo lo que está fuera de Cusco (los anillos de Cusco son agujeros).
function maskOf(geojson) {
  const holes = geojson.features.flatMap((f) => (f.geometry.type === 'MultiPolygon'
    ? f.geometry.coordinates.map((p) => [...p[0]].reverse()) : [[...f.geometry.coordinates[0]].reverse()]))
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], ...holes] } }],
  }
}

function boundsToGeoJson(bounds) {
  if (!bounds) return EMPTY
  const { west, east, south, north } = bounds
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] } }] }
}

// Pantalla de bienvenida (Dante): abierta al entrar salvo ?welcome=0 o ?tutorial=1; se cierra navegando.
const PARAMS_INICIO = new URLSearchParams(window.location.search)
const WELCOME = PARAMS_INICIO.get('welcome') !== '0' && PARAMS_INICIO.get('tutorial') !== '1'

function fitTo(map, bounds, compact = window.innerWidth < 650) {
  // Con la bienvenida abierta, Cusco se encuadra en la mitad derecha (la izquierda la ocupa el texto).
  const welcome = WELCOME && window.innerWidth > 850
  map.fitBounds(bounds, {
    padding: welcome ? { top: 70, right: 70, bottom: 70, left: Math.round(window.innerWidth * 0.52) + 50 }
      : compact ? { top: 76, right: 24, bottom: 112, left: 24 } : { top: 100, right: 160, bottom: 300, left: 430 },
    duration: welcome ? 0 : 900, maxZoom: 8.6,
  })
}

function createPopupContent(title, lines) {
  const root = document.createElement('div')
  root.className = 'fw-popup'
  const heading = document.createElement('b')
  heading.textContent = title
  root.appendChild(heading)
  lines.forEach(({ value, strong = false }) => {
    const element = document.createElement(strong ? 'strong' : 'span')
    element.textContent = value
    root.appendChild(element)
  })
  return root
}

function CategoryBadge({ categoria }) {
  if (!categoria) return <span className="fw-risk fw-risk--bajo"><i />{tr('badge.noAnomaly')}</span>
  const tone = CATEGORIA[categoria] || 'bajo'
  return <span className={`fw-risk fw-risk--${tone}`}><i />{categoria === 'incierta' ? tr('badge.uncertain') : tr('badge.activity', { cat: catLabel(categoria) })}</span>
}

function LayerButton({ active, icon, label, onClick, tone }) {
  return <button className={`fw-layer-button ${active ? 'is-active' : ''}`} onClick={onClick} title={label}><span className={tone}>{createElement(icon, { size: 18 })}</span><b>{label}</b></button>
}

function Metric({ icon, label, value, tone }) {
  return <div className="fw-metric"><span className={tone}>{createElement(icon, { size: 16 })}</span><div><b>{value}</b><small>{label}</small></div></div>
}

function SatelliteSelectionMap({ bounds, focos }) {
  const containerRef = useRef(null)
  const previewMapRef = useRef(null)
  const previewReadyRef = useRef(false)
  const focosRef = useRef(focos)
  const boundsRef = useRef(bounds)
  focosRef.current = focos
  boundsRef.current = bounds

  const fitPreview = useCallback((map, b) => {
    map.fitBounds([[b.west, b.south], [b.east, b.north]], { padding: 22, duration: 0, maxZoom: 12 })
  }, [])

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current, style: SATELLITE_STYLE,
      center: [(boundsRef.current.west + boundsRef.current.east) / 2, (boundsRef.current.south + boundsRef.current.north) / 2],
      zoom: 8, minZoom: 5, maxZoom: 16, attributionControl: false, antialias: true,
    })
    previewMapRef.current = map
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left')
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.on('load', () => {
      map.addSource('preview-focos', { type: 'geojson', data: focosRef.current })
      map.addLayer({
        id: 'preview-heat', type: 'heatmap', source: 'preview-focos', maxzoom: 14,
        paint: {
          'heatmap-weight': ['interpolate', ['linear'], ['get', 'eq_foco'], 0, 0.15, 0.5, 0.6, 1, 1],
          'heatmap-intensity': 1.35,
          'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(255,230,110,0)', 0.25, '#ffe66d', 0.5, '#ff9f32', 0.72, '#ff4c2f', 1, '#9f001f'],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 6, 18, 12, 42],
          'heatmap-opacity': 0.78,
        },
      })
      map.addLayer({
        id: 'preview-points', type: 'circle', source: 'preview-focos',
        paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 3, 12, 7], 'circle-color': '#ff5a3d', 'circle-opacity': 0.95, 'circle-stroke-color': '#fff5dc', 'circle-stroke-width': 1.2 },
      })
      previewReadyRef.current = true
      fitPreview(map, boundsRef.current)
    })
    return () => { previewReadyRef.current = false; map.remove(); previewMapRef.current = null }
  }, [fitPreview])

  useEffect(() => {
    const map = previewMapRef.current
    if (!previewReadyRef.current || !map) return
    map.getSource('preview-focos').setData(focos)
    fitPreview(map, bounds)
  }, [bounds, fitPreview, focos])

  return <div className="fw-satellite-preview"><div ref={containerRef} className="fw-satellite-map"/><span className="fw-satellite-badge"><i/>{tr('sat.badge')}</span><div className="fw-satellite-legend"><span><i className="heat"/>{tr('sat.density')}</span><span><i className="point"/>{tr('sat.point')}</span></div></div>
}

function CalendarPanel({ calendar, mode, setMode, selected, onSelect, onClose, reportUrl }) {
  const byKey = useMemo(() => new Map((calendar?.celdas || []).map((c) => [`${c.anio}-${c.mes}`, c])), [calendar])
  if (!calendar) return null
  const MESES = months()
  const breaks = calendar.cortes_color || []
  const edges = [0, ...breaks]
  return (
    <aside className="fc-calendar" aria-label={tr('cal.aria')}>
      <div className="fc-calendar-head">
        <div><p>{tr('cal.kicker')}</p><h2>{tr('cal.title', { aoi: calendar.aoi.descripcion })}</h2></div>
        <div className="fc-toggle">
          <button className={mode === 'valor' ? 'is-active' : ''} onClick={() => setMode('valor')}>{tr('cal.hotspots')}</button>
          <button className={mode === 'anomalia' ? 'is-active' : ''} onClick={() => setMode('anomalia')}>{tr('cal.anomaly')}</button>
          {reportUrl && <button onClick={() => openReport(reportUrl)} title={tr('report.tip')} aria-label={tr('report.tip')}><FileText size={14}/> {tr('report.short')}</button>}
          <button onClick={onClose} title={tr('cal.close')}><X size={15}/></button>
        </div>
      </div>
      <div className="fc-calendar-grid">
        <table>
          <thead><tr><th/>{MESES.map((m) => <th key={m}>{m}</th>)}</tr></thead>
          <tbody>
            {[...calendar.anios].reverse().map((y) => (
              <tr key={y}>
                <th>{y}</th>
                {MESES.map((_, idx) => {
                  const m = idx + 1
                  const c = byKey.get(`${y}-${m}`)
                  if (!c) return <td key={m} className="is-empty"/>
                  if (c.sin_dato) return <td key={m} className="is-nodata" title={tr('cal.nodataTip', { m: MESES[idx], y })}/>
                  const anomColor = c.anomalia === null ? '#d0d5dd' : divergingColor(c.anomalia)
                  const bg = mode === 'anomalia' ? anomColor : classColor(c.focos_armonizados, breaks)
                  const extrap = c.calidad === 'extrapolado' || c.calidad === 'mixto'
                  const isSel = selected.year === y && selected.month === m
                  const rango = c.incertidumbre ? tr('cal.range', { a: fmt(c.rango[0], 1), b: fmt(c.rango[1], 1) }) : ''
                  const tip = tr('cal.tip', { m: MESES[idx], y, v: fmt(c.focos_armonizados, 2), range: rango, q: calidadLabel(c.calidad), med: fmt(c.mediana_hist, 1), a: c.anomalia ?? '–', cat: catLabel(c.categoria) })
                  return (
                    <td key={m} title={tip} aria-label={tip} role="button" tabIndex={0} onClick={() => onSelect(y, m)}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(y, m) } }}
                      className={[extrap ? 'is-extrap' : '', c.categoria === 'incierta' ? 'is-uncertain' : '', isSel ? 'is-selected' : '', y === 2013 && m === 1 ? 'is-viirs' : ''].join(' ')}
                      style={{ background: bg, color: inkFor(bg) }}>
                      {mode === 'anomalia' ? (c.anomalia === null ? '–' : `${c.anomalia > 0 ? '+' : ''}${c.anomalia.toFixed(1)}`) : fmtFocos(c.focos_armonizados)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="fc-legend">
        {mode === 'valor' ? <>
          <span className="sw" style={{ background: ZERO }}/>0
          {YLORRD.map((color, i) => i < edges.length && <span key={color} className="fc-cls"><span className="sw" style={{ background: color }}/>{edges[i + 1] === undefined ? `> ${fmt(edges[i])}` : `${fmt(edges[i])}–${fmt(edges[i + 1])}`}</span>)}
        </> : <span>{tr('cal.anomLegend')}</span>}
        <span className="fc-cls"><span className="sw is-nodata"/>{tr('legend.nodata')}</span>
        <span className="fc-cls"><span className="sw is-extrap" style={{ background: YLORRD[2] }}/>{tr('legend.extrap')}</span>
        <span className="fc-cls"><span className="sw is-uncertain"/>{tr('legend.uncertain')}</span>
        <span>{tr('legend.note')}</span>
      </div>
    </aside>
  )
}

function FireMapApp() {
  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const mapReadyRef = useRef(false)
  const focosRef = useRef(EMPTY)
  const regionRef = useRef(null)
  const selectionModeRef = useRef(false)

  const [region, setRegion] = useState(null)
  const [departments, setDepartments] = useState([])
  const [selectedRegionCode, setSelectedRegionCode] = useState(CUSCO)
  const [calendar, setCalendar] = useState(null)
  const [selected, setSelected] = useState({ year: LAST_YEAR, month: null })
  const [filterDraft, setFilterDraft] = useState({ region: CUSCO, from: monthStart(LAST_YEAR, 1), to: monthEnd(LAST_YEAR, 12) })
  const [customPeriod, setCustomPeriod] = useState(null)
  const [month, setMonth] = useState(null)
  const [focos, setFocos] = useState(EMPTY)
  const [latency, setLatency] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [activeLayer, setActiveLayer] = useState('surface')
  // Nikal: capas superponibles (densidad y puntos a la vez, o ninguna: solo Cusco).
  const [capasNk, setCapasNk] = useState({ calor: true, puntos: false })
  const [showBoundary, setShowBoundary] = useState(false)
  const [baseMap, setBaseMap] = useState('relief')      // Dante (450cc43): relieve por defecto
  const [calendarMode, setCalendarMode] = useState('valor')
  // ?calendario=0 abre la página sin el calendario (p. ej. para incrustarla en una presentación).
  // Abierto solo en pantallas anchas: en 1440x900 tapaba Cusco (auditoría de Gabriel).
  // En Nikal el calendario nunca se abre solo al cargar (tapaba el mapa en la primera vista).
  const [calendarOpen, setCalendarOpen] = useState(!NK && window.innerWidth >= 1600
    && new URLSearchParams(window.location.search).get('calendario') !== '0')
  const [playing, setPlaying] = useState(false)
  const playableRef = useRef(new Set())
  const yearsRef = useRef(null)
  // Tiempo real (NASA FIRMS NRT, revisiones 10-11): capa aparte de la serie armonizada.
  const [liveOn, setLiveOn] = useState(false)
  const [liveHours, setLiveHours] = useState(24)
  const [live, setLive] = useState(null)              // { body } | { error } | null
  const liveRef = useRef(EMPTY)
  const [simpleOpen, setSimpleOpen] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const [ambitosOpen, setAmbitosOpen] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(true)
  const [layersOpen, setLayersOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectionBounds, setSelectionBounds] = useState(null)
  const [selection, setSelection] = useState(null)
  const [lang, setLangState] = useState(getLang())
  const changeLang = (l) => { setLang(l); setLangState(l) }
  const forceTutorial = new URLSearchParams(window.location.search).get('tutorial') === '1'
  const welcomeOpen = WELCOME
  const [tutorialPrompt, setTutorialPrompt] = useState(AVISO_TUTORIAL)
  const [tutorialOpen, setTutorialOpen] = useState(forceTutorial)
  // Recuadro de Cusco en pantalla (para el paso "Área de estudio" del tutorial), recortado a la ventana.
  const cuscoRect = useCallback(() => {
    const map = mapRef.current
    if (!map || !region) return null
    const b = boundsOf(region)
    const nw = map.project(b.getNorthWest()), se = map.project(b.getSouthEast())
    const r = map.getContainer().getBoundingClientRect()
    const left = Math.max(8, r.left + nw.x), top = Math.max(8, r.top + nw.y)
    const right = Math.min(window.innerWidth - 8, r.left + se.x), bottom = Math.min(window.innerHeight - 8, r.top + se.y)
    return right > left && bottom > top ? { left, top, right, bottom, width: right - left, height: bottom - top } : null
  }, [region])
  // En el celular el panel de datos tapa el mapa: el tutorial lo abre solo en su paso ("Datos y filtros").
  const pasoTutorial = useCallback((paso) => { if (window.innerWidth < 680) setDetailsOpen(paso === 2) }, [])
  const startTutorial = () => { setTutorialPrompt(false); setTutorialOpen(true); setDetailsOpen(true); setSimpleOpen(false); setCompareOpen(false); setAmbitosOpen(false); setToolsOpen(false) }
  const closeTutorial = () => { setTutorialPrompt(false); setTutorialOpen(false) }
  // Juego oculto (tres clics en el logo). La apertura de marca está en index.html.
  const [snake, setSnake] = useState(null)
  const clicsLogo = useRef([])
  const tocarLogo = (e) => {
    if (!NK) return
    const ahora = Date.now()
    clicsLogo.current = [...clicsLogo.current.filter((t) => ahora - t < 900), ahora]
    if (clicsLogo.current.length >= 3) { clicsLogo.current = []; setSnake(e.currentTarget.querySelector('img').getBoundingClientRect()) }
  }
  const MESES = months()
  const selectedRegion = departments.find((d) => d.code === selectedRegionCode) || { code: CUSCO, name: 'Cusco', datos: 'armonizados' }

  const periodo = useMemo(() => {
    if (customPeriod) return { inicio: customPeriod.from.slice(0, 7), fin: customPeriod.to.slice(0, 7), exactFrom: customPeriod.from, exactTo: customPeriod.to, label: `${customPeriod.from} – ${customPeriod.to}` }
    return selected.month
      ? { inicio: ym(selected.year, selected.month), fin: ym(selected.year, selected.month), label: `${months()[selected.month - 1]} ${selected.year}` }
      : { inicio: ym(selected.year, selected.year === FIRST_YEAR ? 11 : 1), fin: ym(selected.year, 12), label: tr('period.year', { y: selected.year }) }
  }, [selected.year, selected.month, lang, customPeriod]) // eslint-disable-line react-hooks/exhaustive-deps
  const aoi = { departamento: selectedRegionCode }
  // Informe técnico: toda la serie; con un mes elegido, ese mes en detalle; con el filtro, ese rango.
  const reportExtra = customPeriod ? { fecha_inicio: periodo.inicio, fecha_fin: periodo.fin }
    : selected.month ? { mes: periodo.inicio } : {}
  const yearCells = useMemo(() => (calendar?.celdas || []).filter((c) => c.anio === selected.year), [calendar, selected.year])
  const yearTotal = useMemo(() => yearCells.reduce((s, c) => s + (c.focos_armonizados || 0), 0), [yearCells])
  const yearMax = useMemo(() => Math.max(1, ...yearCells.map((c) => c.focos_armonizados || 0)), [yearCells])
  const periodCells = useMemo(() => {
    if (!customPeriod) return yearCells
    const fromMonth = customPeriod.from.slice(0, 7)
    const toMonth = customPeriod.to.slice(0, 7)
    return (calendar?.celdas || []).filter((c) => {
      const key = ym(c.anio, c.mes)
      return key >= fromMonth && key <= toMonth
    })
  }, [calendar, customPeriod, yearCells])
  // Día elegido en la cinta: el mapa muestra solo los focos de esa fecha (dentro de los del mes).
  const diaFecha = !customPeriod && selected.month && selected.day ? `${ym(selected.year, selected.month)}-${String(selected.day).padStart(2, '0')}` : null
  const focosDia = useMemo(() => (diaFecha ? filterFocosByDate(focos, diaFecha, diaFecha) : focos), [focos, diaFecha])
  // Capa "Peligro CENEPRED" (en Capas): cómo se reparten los focos del periodo según el nivel de peligro de su
  // unidad, y filtro para ver en el mapa solo los focos de los niveles elegidos.
  const [peligro, setPeligro] = useState({ on: false, nivel: 'provincia', solo: [] })
  const [unidadesPeligro, setUnidadesPeligro] = useState(null)
  useEffect(() => {
    if (!peligro.on) return undefined
    let activo = true
    getAmbitoGeojson(peligro.nivel)
      .then(({ body }) => activo && setUnidadesPeligro({ nivel: peligro.nivel, geojson: body, unidades: prepararUnidades(body) }))
      .catch(() => activo && setUnidadesPeligro(null))
    return () => { activo = false }
  }, [peligro.on, peligro.nivel])
  const clasePeligro = useMemo(() => (peligro.on && unidadesPeligro?.nivel === peligro.nivel
    ? clasificar(focosDia, unidadesPeligro.unidades) : null), [peligro.on, peligro.nivel, unidadesPeligro, focosDia])
  const mapFocos = useMemo(() => {
    if (!clasePeligro || !peligro.solo.length) return focosDia
    const features = focosDia.features.filter((_, i) => peligro.solo.includes(clasePeligro.niveles[i]))
    return { ...focosDia, features, n_focos: features.length }
  }, [focosDia, clasePeligro, peligro.solo])
  // Panel de Capas: aparece a la altura de su botón.
  const capasRef = useRef(null)
  const [capasTop, setCapasTop] = useState(110)
  const abrirCapas = () => {
    const r = capasRef.current?.getBoundingClientRect()
    if (r) setCapasTop(Math.round(r.top))
    setLayersOpen((v) => !v)
  }
  // Focos armonizados por día del mes elegido (suma de eq_foco), para la vista de días de la cinta.
  const diasMes = useMemo(() => {
    if (customPeriod || !selected.month) return null
    const out = Array(new Date(selected.year, selected.month, 0).getDate()).fill(0)
    const pref = ym(selected.year, selected.month)
    for (const f of focos.features || []) {
      const d = f.properties?.fecha_local
      if (d && d.startsWith(pref)) out[Number(d.slice(8, 10)) - 1] += Number(f.properties.eq_foco) || 0
    }
    return out
  }, [focos, selected.year, selected.month, customPeriod])
  playableRef.current = new Set(yearCells.filter((c) => !c.sin_dato).map((c) => c.mes))
  selectionModeRef.current = selectionMode
  focosRef.current = mapFocos

  // Datos base: catálogo regional, contorno, metadatos y calendario de la región elegida.
  useEffect(() => {
    let active = true
    Promise.all([getDepartments(), getCalendar({ departamento: selectedRegionCode })])
      .then(([d, c]) => {
        if (!active) return
        const features = (d.body.geojson?.features || []).filter((f) => f.properties?.code === selectedRegionCode)
        setDepartments(d.body.departamentos || [])
        setRegion({ ...(d.body.geojson || EMPTY), features })
        setCalendar(c.body); setLatency(c.ms)
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [lang, selectedRegionCode])          // en otro idioma, la API devuelve notas y unidad traducidas

  // Focos del periodo seleccionado (mapa) y detalle del mes.
  useEffect(() => {
    let active = true
    setLoading(true)
    setMonth(null)                 // vaciar el detalle: no mostrar números de otro mes mientras carga
    setError('')
    const tasks = [getFocos({ departamento: selectedRegionCode }, periodo.inicio, periodo.fin)]
    if (!customPeriod && selected.month) tasks.push(getMonth({ departamento: selectedRegionCode }, periodo.inicio))
    Promise.all(tasks)
      .then(([f, mo]) => {
        if (!active) return
        setFocos(customPeriod ? filterFocosByDate(f.body, customPeriod.from, customPeriod.to) : f.body); setLatency(f.ms); setMonth(mo ? mo.body : null); setError('')
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [periodo, selected.month, selectedRegionCode, customPeriod])

  // Área dibujada: calendario del área en el periodo y sus focos.
  useEffect(() => {
    if (!selectionBounds) { setSelection(null); return undefined }
    const b = selectionBounds
    const bbox = { bbox: [b.west, b.south, b.east, b.north].map((v) => v.toFixed(4)).join(',') }
    // Las consultas de un área son "pesadas" (cupo de 5 seguidas): durante la reproducción se pausan.
    if (playing) { setSelection({ bbox, paused: true }); return undefined }
    let active = true
    setSelection({ loading: true, bbox })
    Promise.all([getCalendar(bbox, periodo.inicio, periodo.fin), getFocos(bbox, periodo.inicio, periodo.fin)])
      .then(([c, f]) => active && setSelection({ bbox, calendar: c.body, focos: customPeriod ? filterFocosByDate(f.body, customPeriod.from, customPeriod.to) : f.body }))
      .catch((e) => active && setSelection({ bbox, error: e.message }))
    return () => { active = false }
  }, [selectionBounds, periodo, playing, customPeriod])

  // Tiempo real: pide al abrir y cada 5 min (el servidor renueva desde FIRMS cada 15 min).
  useEffect(() => {
    if (!liveOn) { setLive(null); return undefined }
    let active = true
    const load = () => getTiempoReal(liveHours)
      .then((r) => active && setLive({ body: r.body }))
      .catch((e) => active && setLive({ error: e.message }))
    load()
    const timer = window.setInterval(load, 5 * 60 * 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [liveOn, liveHours, lang])

  useEffect(() => {
    liveRef.current = (liveOn && live?.body) ? live.body : EMPTY
    const map = mapRef.current
    if (mapReadyRef.current && map?.getSource('live')) map.getSource('live').setData(liveRef.current)
  }, [live, liveOn])

  // Mantener visible el año elegido en la escala de años (se desplaza si no cabe).
  useEffect(() => {
    const center = () => {
      const el = yearsRef.current
      const a = el?.querySelector('.is-active')
      if (el && a) el.scrollTo({ left: a.offsetLeft - (el.clientWidth - a.offsetWidth) / 2 })
    }
    const t = window.setTimeout(center, 250)          // tras cargar fuentes y diseño
    window.addEventListener('resize', center)
    return () => { window.clearTimeout(t); window.removeEventListener('resize', center) }
  }, [selected.year])

  // Si la línea temporal cambia el periodo, mantener el formulario alineado con esa vista.
  useEffect(() => {
    if (customPeriod) return
    setFilterDraft((current) => ({
      ...current,
      region: selectedRegionCode,
      from: selected.month ? monthStart(selected.year, selected.month) : monthStart(selected.year, selected.year === FIRST_YEAR ? 11 : 1),
      to: selected.month ? monthEnd(selected.year, selected.month) : monthEnd(selected.year, 12),
    }))
  }, [customPeriod, selected, selectedRegionCode])

  // Reproducir: recorre los meses del año seleccionado.
  useEffect(() => {
    if (!playing) return undefined
    const timer = window.setInterval(() => {
      // QA de Erik (7): saltar los meses sin dato (ene-oct de 2000) en vez de mostrar "Sin datos".
      const ok = playableRef.current
      setSelected((s) => {
        let m = s.month || 0
        for (let k = 0; k < 12; k += 1) { m = (m % 12) + 1; if (!ok.size || ok.has(m)) break }
        return { year: s.year, month: m }
      })
    }, 1600)
    return () => window.clearInterval(timer)
  }, [playing])

  useEffect(() => {
    const map = new maplibregl.Map({
      container: mapContainerRef.current, style: MAP_STYLE, center: [-71.97, -13.53], zoom: 6.2,
      minZoom: 4, maxZoom: 14, attributionControl: false, antialias: true,
      // Conserva el dibujo del lienzo: permite guardar el mapa como imagen (METHODOLOGY.md).
      canvasContextAttributes: { preserveDrawingBuffer: true },
    })
    mapRef.current = map
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'NASA FIRMS · FAO GAUL' }), 'bottom-right')
    map.addControl(new maplibregl.NavigationControl({ showCompass: false, visualizePitch: false }), 'bottom-right')
    const canvas = map.getCanvas()
    const canvasContainer = map.getCanvasContainer()
    let dragStart = null
    let drawBox = null
    let suppressNextClick = false

    const pointerPosition = (event) => {
      const rect = canvas.getBoundingClientRect()
      return { x: event.clientX - rect.left, y: event.clientY - rect.top }
    }
    const removeDrawBox = () => { drawBox?.remove(); drawBox = null; dragStart = null }
    const onPointerDown = (event) => {
      if (!selectionModeRef.current || event.button !== 0) return
      event.preventDefault(); event.stopPropagation()
      dragStart = pointerPosition(event)
      drawBox = document.createElement('div')
      drawBox.className = 'fw-selection-box'
      canvasContainer.appendChild(drawBox)
      canvas.setPointerCapture?.(event.pointerId)
    }
    const onPointerMove = (event) => {
      if (!dragStart || !drawBox) return
      event.preventDefault(); event.stopPropagation()
      const current = pointerPosition(event)
      drawBox.style.left = `${Math.min(dragStart.x, current.x)}px`
      drawBox.style.top = `${Math.min(dragStart.y, current.y)}px`
      drawBox.style.width = `${Math.abs(current.x - dragStart.x)}px`
      drawBox.style.height = `${Math.abs(current.y - dragStart.y)}px`
    }
    const onPointerUp = (event) => {
      if (!dragStart || !drawBox) return
      event.preventDefault(); event.stopPropagation()
      const end = pointerPosition(event)
      if (Math.abs(end.x - dragStart.x) >= 8 && Math.abs(end.y - dragStart.y) >= 8) {
        suppressNextClick = true
        window.setTimeout(() => { suppressNextClick = false }, 0)
        const first = map.unproject([Math.min(dragStart.x, end.x), Math.max(dragStart.y, end.y)])
        const second = map.unproject([Math.max(dragStart.x, end.x), Math.min(dragStart.y, end.y)])
        setSelectionBounds({ west: first.lng, south: first.lat, east: second.lng, north: second.lat })
        if (window.innerWidth < 650) setDetailsOpen(false)
        setSelectionMode(false)
      }
      removeDrawBox()
      canvas.releasePointerCapture?.(event.pointerId)
    }
    canvas.addEventListener('pointerdown', onPointerDown, true)
    canvas.addEventListener('pointermove', onPointerMove, true)
    canvas.addEventListener('pointerup', onPointerUp, true)
    canvas.addEventListener('pointercancel', removeDrawBox, true)

    map.on('load', () => {
      map.addSource('relief-imagery', { type: 'raster', tileSize: 256, attribution: 'Esri, Vantor, Earthstar Geographics, and the GIS User Community', tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'] })
      map.addSource('relief-reference', { type: 'raster', tileSize: 256, tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'] })
      map.addLayer({ id: 'relief-imagery-layer', type: 'raster', source: 'relief-imagery', layout: { visibility: 'visible' }, paint: { 'raster-saturation': -0.12, 'raster-contrast': 0.08, 'raster-brightness-min': 0.08, 'raster-brightness-max': 0.92 } })
      map.addLayer({ id: 'relief-reference-layer', type: 'raster', source: 'relief-reference', layout: { visibility: 'visible' }, paint: { 'raster-opacity': 0.82 } })
      map.addSource('cusco-mask', { type: 'geojson', data: EMPTY })
      map.addSource('cusco-area', { type: 'geojson', data: EMPTY })
      map.addSource('focos', { type: 'geojson', data: EMPTY })
      map.addSource('selection-area', { type: 'geojson', data: EMPTY })
      map.addLayer({ id: 'cusco-mask', type: 'fill', source: 'cusco-mask', paint: { 'fill-color': MAPA.mascara, 'fill-opacity': NK ? 0.46 : 0.38 } })
      map.addLayer({ id: 'study-area-fill', type: 'fill', source: 'cusco-area', paint: { 'fill-color': MAPA.areaRelleno, 'fill-opacity': 0.035 } })
      map.addLayer({ id: 'study-area-glow', type: 'line', source: 'cusco-area', paint: { 'line-color': MAPA.area, 'line-width': 4, 'line-opacity': 0.18, 'line-blur': 4 } })
      map.addLayer({ id: 'study-area-border', type: 'line', source: 'cusco-area', paint: { 'line-color': MAPA.area, 'line-width': 1.8, 'line-opacity': 0.9, 'line-dasharray': [2, 1.6] } })
      map.addLayer({
        id: 'fire-heat', type: 'heatmap', source: 'focos', maxzoom: 12, layout: { visibility: 'visible' },
        paint: {
          // Peso = aporte del foco a la serie armonizada (eq_foco); sin FRP.
          'heatmap-weight': ['interpolate', ['linear'], ['get', 'eq_foco'], 0, 0.04, 0.25, 0.3, 1, 0.75, 3, 1],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 5, 0.5, 8, 0.9, 11, 1.3],
          'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(245,158,11,0)', 0.16, 'rgba(245,158,11,0)', 0.24, 'rgba(245,158,11,.22)',
            0.36, '#fde68a', 0.52, '#f59e0b', 0.68, '#ea580c', 0.84, '#dc2626', 1, '#7f1d1d'],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 5, 10, 7, 18, 10, 34],
          'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 5, 0.8, 11, 0.5],
        },
      })
      map.addLayer({
        id: 'fire-points', type: 'circle', source: 'focos', layout: { visibility: 'none' },
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 2.5, 10, 6],
          'circle-color': ['match', ['get', 'sensor'], 'MODIS', '#ff9b3f', '#f33932'],
          'circle-opacity': ['case', ['==', ['get', 'en_serie'], 1], 0.92, 0.35],
          'circle-stroke-color': '#fff4df', 'circle-stroke-width': 1,
        },
      })
      map.addSource('live', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'live-points', type: 'circle', source: 'live', layout: { visibility: 'none' },
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 4, 10, 8],
          // Color por antigüedad: < 6 h, 6-24 h, más de 24 h.
          'circle-color': ['step', ['get', 'horas_atras'], '#ff1f4b', 6, '#ff7a1a', 24, '#ffc24b'],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.6, 'circle-opacity': 0.95,
        },
      })
      map.on('mouseenter', 'live-points', () => { map.getCanvas().style.cursor = 'pointer' })
      map.on('mouseleave', 'live-points', () => { map.getCanvas().style.cursor = '' })
      map.on('click', 'live-points', (event) => {
        if (suppressNextClick) return
        const p = event.features?.[0]?.properties
        if (!p) return
        new maplibregl.Popup({ offset: 12, className: 'fw-map-popup' })
          .setLngLat(event.features[0].geometry.coordinates)
          .setDOMContent(createPopupContent(tr('liveLayer.popupTitle', { inst: p.instrumento, sat: p.satelite }), [
            { value: `${p.fecha_hora_local} · ${tr('liveLayer.ago', { h: fmt(Number(p.horas_atras), 1) })}`, strong: true },
            { value: tr('liveLayer.conf', { c: tr(`conf.${p.confianza}`) }) },
            { value: tr('liveLayer.notHarm') },
          ]))
          .addTo(map)
      })
      map.addLayer({ id: 'selection-area-fill', type: 'fill', source: 'selection-area', paint: { 'fill-color': MAPA.seleccion, 'fill-opacity': 0.12 } })
      map.addLayer({ id: 'selection-area-line', type: 'line', source: 'selection-area', paint: { 'line-color': MAPA.seleccion, 'line-width': 2.5, 'line-dasharray': [2, 1.4] } })

      map.on('mouseenter', 'fire-points', () => { map.getCanvas().style.cursor = 'pointer' })
      map.on('mouseleave', 'fire-points', () => { map.getCanvas().style.cursor = '' })
      map.on('click', 'fire-points', (event) => {
        if (suppressNextClick) return
        const p = event.features?.[0]?.properties
        if (!p) return
        new maplibregl.Popup({ offset: 12, className: 'fw-map-popup' })
          .setLngLat(event.features[0].geometry.coordinates)
          .setDOMContent(createPopupContent(tr('popup.title', { sensor: p.sensor, sat: p.satelite }), [
            { value: `${p.fecha_local} · ${String(p.hora_utc).slice(0, 2)}:${String(p.hora_utc).slice(2)} UTC` },
            { value: Number(p.en_serie) === 1 ? tr('popup.weight', { v: fmt(Number(p.eq_foco), 3) }) : tr('popup.out'), strong: true },
            { value: p.calidad ? tr('popup.quality', { q: calidadLabel(p.calidad) }) : tr('popup.noweight') },
          ]))
          .addTo(map)
      })
      mapReadyRef.current = true
      map.getSource('focos').setData(focosRef.current)
      map.getSource('live').setData(liveRef.current)
      if (regionRef.current) {
        map.getSource('cusco-area').setData(regionRef.current)
        map.getSource('cusco-mask').setData(maskOf(regionRef.current))
        fitTo(map, boundsOf(regionRef.current))
      }
    })
    return () => {
      mapReadyRef.current = false
      canvas.removeEventListener('pointerdown', onPointerDown, true)
      canvas.removeEventListener('pointermove', onPointerMove, true)
      canvas.removeEventListener('pointerup', onPointerUp, true)
      canvas.removeEventListener('pointercancel', removeDrawBox, true)
      removeDrawBox()
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    regionRef.current = region
    const map = mapRef.current
    if (!region || !mapReadyRef.current || !map) return
    map.getSource('cusco-area').setData(region)
    map.getSource('cusco-mask').setData(maskOf(region))
    fitTo(map, boundsOf(region))
  }, [region])

  useEffect(() => {
    const map = mapRef.current
    if (mapReadyRef.current && map?.getSource('focos')) map.getSource('focos').setData(mapFocos)
  }, [mapFocos])

  // Unidades pintadas por nivel de peligro bajo los focos (capa Peligro CENEPRED); con filtro, se atenúan las demás.
  useEffect(() => {
    const map = mapRef.current
    if (!mapReadyRef.current || !map) return
    const visible = Boolean(peligro.on && !liveOn && unidadesPeligro?.nivel === peligro.nivel)
    if (visible && !map.getSource('peligro-unidades')) {
      map.addSource('peligro-unidades', { type: 'geojson', data: unidadesPeligro.geojson, promoteId: 'codigo' })
      const antes = map.getLayer('fire-heat') ? 'fire-heat' : undefined
      map.addLayer({ id: 'peligro-fill', type: 'fill', source: 'peligro-unidades', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.35 } }, antes)
      map.addLayer({ id: 'peligro-line', type: 'line', source: 'peligro-unidades', paint: { 'line-color': '#141210', 'line-width': 0.8, 'line-opacity': 0.7 } }, antes)
    } else if (visible) {
      map.getSource('peligro-unidades').setData(unidadesPeligro.geojson)
    }
    if (!map.getLayer('peligro-fill')) return
    // Color = nivel de peligro de la unidad; intensidad = sus focos en el año, mes o día de la cinta.
    if (visible && clasePeligro) {
      ;(unidadesPeligro.geojson.features || []).forEach((f) => map.setFeatureState(
        { source: 'peligro-unidades', id: f.properties.codigo }, { act: clasePeligro.actividad.get(f.properties.codigo) || 0 }))
    }
    const intensidad = ['interpolate', ['linear'], ['coalesce', ['feature-state', 'act'], 0], 0, 0.05, 1, 0.68]
    map.setPaintProperty('peligro-fill', 'fill-opacity', peligro.solo.length
      ? ['case', ['in', ['get', 'nivel_peligro'], ['literal', peligro.solo]], intensidad, 0.03] : intensidad)
    ;['peligro-fill', 'peligro-line'].forEach((id) => map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none'))
  }, [peligro, unidadesPeligro, liveOn, clasePeligro])

  // Al cerrar Herramientas se cierra también el panel de Capas.
  useEffect(() => { if (NK && !toolsOpen) setLayersOpen(false) }, [toolsOpen])

  useEffect(() => {
    const map = mapRef.current
    if (mapReadyRef.current && map?.getSource('selection-area')) map.getSource('selection-area').setData(boundsToGeoJson(selectionBounds))
  }, [selectionBounds])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReadyRef.current || !map) return
    map.getContainer().classList.toggle('is-selecting', selectionMode)
    const handlers = [map.dragPan, map.touchZoomRotate, map.doubleClickZoom]
    handlers.forEach((h) => (selectionMode ? h.disable() : h.enable()))
  }, [selectionMode])

  useEffect(() => {
    const cancel = (event) => { if (event.key === 'Escape') setSelectionMode(false) }
    window.addEventListener('keydown', cancel)
    return () => window.removeEventListener('keydown', cancel)
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReadyRef.current || !map) return
    // Dos modos que no se mezclan: la serie histórica o las detecciones en vivo.
    const vis = (on) => (on ? 'visible' : 'none')
    map.setLayoutProperty('fire-heat', 'visibility', vis(!liveOn && (NK ? capasNk.calor : activeLayer === 'surface')))
    map.setLayoutProperty('fire-points', 'visibility', vis(!liveOn && (NK ? capasNk.puntos : activeLayer === 'points')))
    map.setLayoutProperty('selection-area-fill', 'visibility', vis(!liveOn))
    map.setLayoutProperty('selection-area-line', 'visibility', vis(!liveOn))
    map.setLayoutProperty('live-points', 'visibility', vis(liveOn))
  }, [activeLayer, liveOn, capasNk])

  useEffect(() => {
    const map = mapRef.current
    if (!mapReadyRef.current || !map?.getLayer('relief-imagery-layer')) return
    const visibility = baseMap === 'relief' ? 'visible' : 'none'
    map.setLayoutProperty('relief-imagery-layer', 'visibility', visibility)
    map.setLayoutProperty('relief-reference-layer', 'visibility', visibility)
  }, [baseMap])

  // "Límite" resalta Cusco sin apagar la densidad ni los puntos.
  useEffect(() => {
    const map = mapRef.current
    if (!mapReadyRef.current || !map) return
    map.setPaintProperty('study-area-fill', 'fill-opacity', showBoundary ? 0.22 : 0.035)
    map.setPaintProperty('study-area-border', 'line-width', showBoundary ? 3 : 1.8)
  }, [showBoundary])

  // Capítulos: un solo panel abierto a la vez (mismo comportamiento que los lanzadores de Dante).
  const openChapter = (id) => {
    const was = { data: detailsOpen, simple: simpleOpen, compare: compareOpen, ambitos: ambitosOpen }[id]
    setDetailsOpen(false); setSimpleOpen(false); setCompareOpen(false); setAmbitosOpen(false)
    if (id === 'ambitos') clearSelection()
    if (!was) ({ data: setDetailsOpen, simple: setSimpleOpen, compare: setCompareOpen, ambitos: setAmbitosOpen })[id](true)
  }
  const selectMonth = (year, m) => { setPlaying(false); setCustomPeriod(null); setSelected({ year, month: m }) }
  const elegirDia = (d) => { setPlaying(false); setSelected((s) => ({ ...s, day: s.day === d ? null : d })) }
  const shiftMonth = (delta) => setSelected((s) => {
    const k = Math.min(LAST_YEAR * 12 + 11, Math.max(FIRST_YEAR * 12 + 10, s.year * 12 + s.month - 1 + delta))
    return { year: Math.floor(k / 12), month: (k % 12) + 1 }
  })
  const shiftYear = (delta) => { setCustomPeriod(null); setSelected((s) => ({ year: Math.min(LAST_YEAR, Math.max(FIRST_YEAR, s.year + delta)), month: null })) }
  const toggleSelectionMode = () => {
    setPlaying(false)
    setSelectionMode((active) => { if (!active) setSelectionBounds(null); return !active })
  }
  const clearSelection = () => { setSelectionMode(false); setSelectionBounds(null) }
  // Cambiar de modo: lo abierto del histórico se conserva para cuando se vuelva.
  const goLive = () => { setPlaying(false); setSelectionMode(false); setCompareOpen(false); setLiveOn(true) }
  const goHistoric = () => setLiveOn(false)
  const focusRegion = () => { if (mapReadyRef.current && region) fitTo(mapRef.current, boundsOf(region)) }
  const applyFilters = (event) => {
    event.preventDefault()
    if (filterDraft.from > filterDraft.to) { setError(tr('filter.invalid')); return }
    const [year] = filterDraft.to.split('-').map(Number)
    setPlaying(false); setError(''); setSelectionBounds(null)
    setSelectedRegionCode(filterDraft.region)
    setSelected({ year, month: null })
    setCustomPeriod({ from: filterDraft.from, to: filterDraft.to })
  }
  const clearFilters = () => {
    const initial = { region: CUSCO, from: monthStart(LAST_YEAR, 1), to: monthEnd(LAST_YEAR, 12) }
    setPlaying(false); setError(''); setSelectionBounds(null)
    setFilterDraft(initial); setSelectedRegionCode(CUSCO); setSelected({ year: LAST_YEAR, month: null }); setCustomPeriod(null)
  }

  const runDownload = async (aoiParams, label) => {
    setNotice(tr('csv.preparing'))
    try {
      const r = await downloadCsv(aoiParams, periodo.inicio, periodo.fin)
      setNotice(tr('csv.done', { label, n: fmt(r.rows), total: fmt(r.total, 0) }))
      window.setTimeout(() => setNotice(''), 8000)
    } catch (e) { setNotice(e.message) }
  }

  const selectionArea = useMemo(() => {
    if (!selectionBounds) return 0
    const mid = (selectionBounds.north + selectionBounds.south) / 2 * Math.PI / 180
    return Math.abs(selectionBounds.east - selectionBounds.west) * 111.32 * Math.cos(mid) * Math.abs(selectionBounds.north - selectionBounds.south) * 110.57
  }, [selectionBounds])

  const summaryValue = customPeriod
    ? (focos.features || []).reduce((sum, feature) => sum + (Number(feature.properties?.eq_foco) || 0), 0)
    : selected.month ? month?.focos_armonizados : yearTotal
  return (
    <div className={`fw-app ${liveOn ? 'is-live' : ''} ${NK ? 'nk' : ''} ${welcomeOpen ? 'is-welcome' : ''}`}>
      <div ref={mapContainerRef} className="fw-map" aria-label={tr('map.aria')} />
      {welcomeOpen && <IntroWelcome lang={lang} onLanguage={changeLang}/>}
      <div className="fw-nubel-brand nk-brand" aria-label="Nikal Cusco" onClick={tocarLogo} style={snake ? { visibility: 'hidden' } : undefined}><img src="./nikal-icono.svg" alt="Nikal"/></div>
      <div className="fc-mode" role="group" aria-label={tr('mode.label')}>
        <button className={!liveOn ? 'is-active' : ''} aria-pressed={!liveOn} title={tr('mode.historic')} onClick={goHistoric}><I.historico size={14}/><span>{tr('mode.historic')}</span></button>
        <button className={liveOn ? 'is-active live' : ''} aria-pressed={liveOn} title={tr('mode.live')} onClick={goLive}><I.vivo size={14}/><span>{tr('mode.live')}</span></button>
      </div>
      {liveOn && <aside className="fc-live-panel" aria-label={tr('rail.liveTitle')}>
        <header><p><i/>{tr('liveLayer.kicker')}</p><button onClick={goHistoric} title={tr('mode.backHistoric')} aria-label={tr('mode.backHistoric')}><X size={15}/></button></header>
        <div className="fc-live-hours" role="group" aria-label={tr('liveLayer.window')}>
          {[24, 48, 120].map((h) => <button key={h} className={liveHours === h ? 'is-active' : ''} aria-pressed={liveHours === h} onClick={() => setLiveHours(h)}>{tr(`liveLayer.h${h}`)}</button>)}
        </div>
        {!live && <p className="fc-live-msg">{tr('summary.loading')}</p>}
        {live?.error && <p className="fc-live-msg is-error">{live.error}</p>}
        {live?.body && (() => {
          const m = live.body.metadata
          const upd = new Date(m.actualizado_utc.replace('Z', ':00Z')).toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit', timeZone: 'America/Lima' })
          return <>
            <h3>{m.detecciones === 1 ? tr('liveLayer.count1') : tr('liveLayer.count', { n: fmt(m.detecciones) })}</h3>
            <p className="fc-live-msg">{m.ultima_deteccion_local ? tr('liveLayer.last', { t: m.ultima_deteccion_local }) : tr('liveLayer.none')}</p>
            {m.desactualizado && <p className="fc-live-msg is-error">{tr('liveLayer.stale')}</p>}
            <small>{tr('liveLayer.updated', { t: upd })} · {m.fuentes.join(', ')}</small>
            <button className="fc-live-back" onClick={goHistoric}><CalendarDays size={14}/>{tr('mode.backHistoric')}</button>
          </>
        })()}
      </aside>}
      {NK ? <ChapterRail active={detailsOpen ? 'data' : simpleOpen ? 'simple' : compareOpen ? 'compare' : ambitosOpen ? 'ambitos' : null} onPick={openChapter}/> : <>
      <button className={`fc-data-launcher ${detailsOpen ? 'is-active' : ''}`} aria-label={tr('data.open')} aria-expanded={detailsOpen} onClick={() => { setAmbitosOpen(false); setSimpleOpen(false); setCompareOpen(false); setDetailsOpen((v) => !v) }}><Database size={19}/><span>{tr('data.label')}</span></button>
      <button className={`fc-data-launcher fc-simple-launcher ${simpleOpen ? 'is-active' : ''}`} aria-label={tr('rail.simpleTitle')} aria-expanded={simpleOpen} onClick={() => { setAmbitosOpen(false); setDetailsOpen(false); setCompareOpen(false); setSimpleOpen((v) => !v) }}><MessageCircleQuestion size={19}/><span>{tr('rail.simple')}</span></button>
      <button className={`fc-data-launcher fc-compare-launcher ${compareOpen ? 'is-active' : ''}`} aria-label={tr('compare.open')} aria-expanded={compareOpen} onClick={() => { setAmbitosOpen(false); setDetailsOpen(false); setSimpleOpen(false); setCompareOpen((v) => !v) }}><ArrowLeftRight size={19}/><span>{tr('compare.button')}</span></button>
      <button className={`fc-data-launcher fc-ambitos-launcher ${ambitosOpen ? 'is-active' : ''}`} aria-label={tr('rail.ambitosTitle')} title={tr('rail.ambitosTitle')} aria-expanded={ambitosOpen} onClick={() => { setDetailsOpen(false); setSimpleOpen(false); setCompareOpen(false); clearSelection(); setAmbitosOpen((v) => !v) }}><Landmark size={19}/><span>{tr('rail.ambitos')}</span></button>
      </>}
      <div className="fc-map-menu">
        <div className="fc-lang" role="group" aria-label={tr('lang.title')}>{LANGS.map((l) => <button key={l} className={l === lang ? 'is-active' : ''} aria-pressed={l === lang} onClick={() => changeLang(l)}>{l.toUpperCase()}</button>)}</div>
        <button className={`fc-menu-toggle ${toolsOpen ? 'is-open' : ''}`} aria-label={tr('rail.label')} aria-expanded={toolsOpen} onClick={() => setToolsOpen((v) => !v)}><I.capas size={21}/>{NK && <span className="nk-tip"><b>{tr('nk.tip.tools')}</b><small>{tr('nk.tip.tools.sub')}</small></span>}</button>
        {(toolsOpen || NK) && <nav className={`fw-rail ${NK ? 'nk-rail' : ''} ${toolsOpen ? 'is-open' : ''}`} aria-label={tr('rail.label')} aria-hidden={!toolsOpen} inert={toolsOpen ? undefined : ''} onClickCapture={goHistoric}>
          {!NK && <button className="is-active" title={NK ? undefined : tr('rail.hotspotsTitle')} aria-label={tr('rail.hotspotsTitle')} onClick={() => { focusRegion(); setDetailsOpen(true); setActiveLayer('surface') }}><I.focos size={19}/><span>{tr('rail.hotspots')}</span>{NK && <span className="nk-tip"><b>{tr('rail.hotspots')}</b><small>{tr('nk.tip.hotspots.sub')}</small></span>}</button>}
          {!NK && <button className={calendarOpen ? 'is-active' : ''} title={NK ? undefined : tr('rail.calendar')} aria-label={tr('rail.calendar')} onClick={() => setCalendarOpen((v) => !v)}><I.calendario size={19}/><span>{tr('rail.calendar')}</span>{NK && <span className="nk-tip"><b>{tr('rail.calendar')}</b><small>{tr('nk.tip.calendar.sub')}</small></span>}</button>}
          {NK && <button ref={capasRef} className={layersOpen ? 'is-active' : ''} title={NK ? undefined : tr('rail.layers')} aria-label={tr('rail.layers')} onClick={abrirCapas}><I.ajustes size={19}/><span>{tr('rail.layers')}</span>{NK && <span className="nk-tip"><b>{tr('rail.layers')}</b><small>{tr('nk.tip.layers.sub')}</small></span>}</button>}
          <button className={selectionMode ? 'is-active select' : ''} title={NK ? undefined : tr('rail.areaTitle')} aria-label={tr('rail.areaTitle')} onClick={toggleSelectionMode}><I.area size={19}/><span>{tr('rail.area')}</span>{NK && <span className="nk-tip"><b>{tr('rail.area')}</b><small>{tr('nk.tip.area.sub')}</small></span>}</button>
          {!NK && <button className={layersOpen ? 'is-active' : ''} title={NK ? undefined : tr('rail.layers')} aria-label={tr('rail.layers')} onClick={() => setLayersOpen((v) => !v)}><I.ajustes size={19}/><span>{tr('rail.layers')}</span>{NK && <span className="nk-tip"><b>{tr('rail.layers')}</b><small>{tr('nk.tip.layers.sub')}</small></span>}</button>}
        </nav>}
        {NK && <button className={`fc-menu-toggle nk-compare-btn ${compareOpen ? 'is-open' : ''}`} aria-label={tr('nk.ch.compare')} aria-pressed={compareOpen} onClick={() => openChapter('compare')}><IcoPxComparar size={20}/>{NK && <span className="nk-tip"><b>{tr('nk.ch.compare')}</b><small>{tr('nk.ch.compare.sub')}</small></span>}</button>}
        {NK && <button className={`fc-menu-toggle nk-cal-btn ${calendarOpen ? 'is-open' : ''}`} aria-label={tr('rail.calendar')} aria-pressed={calendarOpen} onClick={() => { goHistoric(); setCalendarOpen((v) => !v) }}><I.calendario size={20}/>{NK && <span className="nk-tip"><b>{tr('rail.calendar')}</b><small>{tr('nk.tip.calendar.sub')}</small></span>}</button>}
        {NK && <button className="fc-menu-toggle nk-tutorial-btn" aria-label={lang === 'es' ? 'Abrir tutorial' : 'Open tutorial'} onClick={startTutorial}><CircleHelp size={20}/><span className="nk-tip"><b>Tutorial</b><small>{lang === 'es' ? 'Recorrido guiado' : 'Guided tour'}</small></span></button>}
      </div>
      {detailsOpen && <aside className="fw-summary">
        <div className="fw-summary-head"><div><p>{selectedRegion.name.toUpperCase()} · {tr('summary.series')}</p><h1>{tr('filter.title')}</h1><span>{periodo.label}{!customPeriod && month?.calidad ? ` · ${calidadLabel(month.calidad)}` : ''}</span></div><button onClick={() => setDetailsOpen(false)} title={tr('btn.close')} aria-label={tr('btn.close')}><X size={17}/></button></div>
        <form className="fc-filter-panel" onSubmit={applyFilters}>
          <p>{tr('filter.hint')}</p>
          <label htmlFor="fc-region"><span>{tr('filter.department')}</span><select id="fc-region" value={filterDraft.region} onChange={(e) => setFilterDraft((f) => ({ ...f, region: e.target.value }))}>{departments.map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}</select></label>
          <div className="fc-filter-period"><strong><CalendarDays/>{tr('compare.dateRange')}</strong><div>
            <label htmlFor="fc-from"><span>{tr('filter.from')}</span><input id="fc-from" type="date" min="2000-11-01" max="2025-12-31" value={filterDraft.from} onChange={(e) => setFilterDraft((f) => ({ ...f, from: e.target.value }))}/></label>
            <label htmlFor="fc-to"><span>{tr('filter.to')}</span><input id="fc-to" type="date" min="2000-11-01" max="2025-12-31" value={filterDraft.to} onChange={(e) => setFilterDraft((f) => ({ ...f, to: e.target.value }))}/></label>
          </div></div>
          <button className="fc-filter-apply" type="submit"><SlidersHorizontal size={14}/>{tr('filter.apply')}</button>
          <button className="fc-filter-clear" type="button" onClick={clearFilters}>{tr('filter.clear')}</button>
          <small><i/>{tr('filter.validatedOnly')}</small>
        </form>
        <div className="fw-summary-status">{!customPeriod && selected.month ? <CategoryBadge categoria={month?.categoria}/> : <span className="fw-risk fw-risk--bajo"><i/>{customPeriod ? tr('filter.active') : tr('summary.yearTotal')}</span>}<span>{loading ? tr('summary.loading') : tr('summary.onMap', { n: fmt(focos.n_focos || 0) })}</span></div>
        {error && <div className="fw-error"><ShieldAlert size={16}/>{error}</div>}
        <div className="fw-metrics">
          <Metric icon={I.focos} label={tr('metric.hotspots')} value={fmtFocos(summaryValue)} tone="red"/>
          <Metric icon={I.habitual} label={!customPeriod && selected.month ? tr('metric.monthMedian') : tr('metric.monthsFire')} value={!customPeriod && selected.month ? fmt(month?.mediana_hist, 1) : periodCells.filter((c) => c.focos_armonizados > 0).length} tone="orange"/>
          <Metric icon={I.calendario} label={!customPeriod && selected.month ? tr('metric.anomaly') : tr('metric.cellDays')} value={!customPeriod && selected.month ? (month?.anomalia ?? '–') : fmt(periodCells.reduce((s, c) => s + (c.celdas_dia || 0), 0))} tone="green"/>
          <Metric icon={I.satelite} label={tr('metric.modisViirs')} value={!customPeriod && selected.month ? `${fmt(month?.focos_modis)} / ${fmt(month?.focos_viirs)}` : `${fmt(periodCells.reduce((s, c) => s + (c.focos_modis || 0), 0))} / ${fmt(periodCells.reduce((s, c) => s + (c.focos_viirs || 0), 0))}`} tone="blue"/>
        </div>
        {!customPeriod && selected.month && month?.incertidumbre > 0 && <p className="fc-margin">{tr('summary.margin', { a: fmt(month.rango[0], 1), b: fmt(month.rango[1], 1) })}</p>}
        <div className="fw-sensor-row"><span><i className="modis"/>MODIS · 1 km</span><span><i className="viirs"/>VIIRS · 375 m</span></div>
        <div className="fw-summary-actions"><button onClick={() => setCalendarOpen(true)}><CalendarDays size={16}/>{tr('rail.calendar')}</button><button onClick={() => runDownload(aoi, selectedRegion.name)}><Download size={16}/>CSV</button><button onClick={() => openReport(informeUrl(aoi, reportExtra))} title={tr('report.tip')}><FileText size={16}/>{tr('report.short')}</button></div>
        {notice && <p className="fc-notice">{notice}</p>}
      </aside>}
      {layersOpen && !selectionBounds && NK && <aside className="fw-layers nk-capas" style={{ top: capasTop }} aria-label={tr('layers.title')}>
        <header className="nk-capas-head"><b>{tr('layers.title')}</b>
          {(capasNk.calor || capasNk.puntos || showBoundary || peligro.on)
            ? <button className="nk-capas-todas" onClick={() => { setCapasNk({ calor: false, puntos: false }); setShowBoundary(false); setPeligro((p) => ({ ...p, on: false, solo: [] })) }}>{tr('nk.capas.none')}</button>
            : <button className="nk-capas-todas" onClick={() => setCapasNk({ calor: true, puntos: false })}>{tr('nk.capas.reset')}</button>}
        </header>
        <div className="nk-capas-base">
          <LayerButton active={capasNk.calor} icon={ThermometerSun} label={tr('layers.density')} tone="heat" onClick={() => setCapasNk((c) => ({ ...c, calor: !c.calor }))}/>
          <LayerButton active={capasNk.puntos} icon={MapPin} label={tr('layers.points')} tone="points" onClick={() => setCapasNk((c) => ({ ...c, puntos: !c.puntos }))}/>
          <LayerButton active={showBoundary} icon={Layers3} label={tr('layers.boundary')} tone="boundary" onClick={() => setShowBoundary((v) => !v)}/>
        </div>
        <PeligroFiltro peligro={peligro} setPeligro={setPeligro} clase={clasePeligro}/>
      </aside>}
      {layersOpen && !selectionBounds && !NK && <aside className="fw-layers">
        <div className="fw-layers-title"><span>{tr('layers.title')}</span><SlidersHorizontal size={15}/></div>
        <LayerButton active={activeLayer === 'surface'} icon={ThermometerSun} label={tr('layers.density')} tone="heat" onClick={() => setActiveLayer('surface')}/>
        <LayerButton active={activeLayer === 'points'} icon={MapPin} label={tr('layers.points')} tone="points" onClick={() => setActiveLayer('points')}/>
        <LayerButton active={showBoundary} icon={Layers3} label={tr('layers.boundary')} tone="boundary" onClick={() => setShowBoundary((v) => !v)}/>
      </aside>}
      <aside className="fw-display-dock" aria-label={tr('basemap.dock')}>
        <div className="fw-display-modes" role="group" aria-label={tr('basemap.title')}>
          <button className={baseMap === 'standard' ? 'is-active' : ''} aria-pressed={baseMap === 'standard'} title={tr('basemap.standard')} onClick={() => setBaseMap('standard')}><I.plano size={14}/><span>{tr('basemap.standard')}</span></button>
          <button className={baseMap === 'relief' ? 'is-active' : ''} aria-pressed={baseMap === 'relief'} title={tr('basemap.relief')} onClick={() => setBaseMap('relief')}><I.relieve size={14}/><span>{tr('basemap.relief')}</span></button>
        </div>
        {liveOn ? <div className="fw-heat-legend fc-dock-points"><header><span>{tr('liveLayer.age')}</span></header><p><i style={{ background: '#ff1f4b' }}/>{'< 6 h'}</p><p><i style={{ background: '#ff7a1a' }}/>6–24 h</p><p><i style={{ background: '#ffc24b' }}/>{'> 24 h'}</p></div>
          : (NK ? capasNk.puntos && !capasNk.calor : activeLayer === 'points')
          ? <div className="fw-heat-legend fc-dock-points"><header><span>{tr('layers.pointsLegend')}</span></header><p><i className="modis"/>MODIS</p><p><i className="viirs"/>VIIRS</p><p><i className="outside"/>{tr('layers.outside')}</p></div>
          : <div className="fw-heat-legend"><header><span>{tr('layers.scaleDensity')}</span></header><i/><div><span>{tr('scale.low')}</span><span>{tr('scale.mid')}</span><span>{tr('scale.high')}</span></div></div>}
      </aside>
      <div className="fw-map-meta"><button onClick={focusRegion}><MapPin size={13}/>{selectedRegion.name}</button><span><Satellite size={13}/>MODIS + VIIRS</span><span><CalendarDays size={13}/>{periodo.label}</span></div>
      {selectionMode && <div className="fw-draw-hint"><Scan size={20}/><div><b>{tr('draw.title')}</b><span>{tr('draw.hint')}</span></div><button onClick={() => setSelectionMode(false)} title={tr('btn.cancel')}><X size={16}/></button></div>}
      {selectionBounds && !simpleOpen && <aside className="fw-selection-card">
        <div className="fw-selection-head"><div><p>{tr('sel.kicker')}</p><h2>{tr('sel.title')}</h2><span>{periodo.label} · {tr('sel.within')}</span></div><button onClick={clearSelection} title={tr('sel.clear')}><Trash2 size={17}/></button></div>
        <SatelliteSelectionMap bounds={selectionBounds} focos={selection?.focos || EMPTY}/>
        <div className="fw-selection-source"><span>{tr('sel.source')}</span><b>Esri World Imagery · NASA FIRMS</b></div>
        {selection?.paused && <p className="fc-notice">{tr('sel.paused')}</p>}
        {selection?.error ? <div className="fw-error"><ShieldAlert size={16}/>{selection.error}</div> : <div className="fw-selection-grid">
          <article><span>{tr('metric.hotspots')}</span><b>{selection?.calendar ? fmtFocos(selection.calendar.total_focos_armonizados) : '…'}</b></article>
          <article><span>{tr('metric.cellDays')}</span><b>{selection?.calendar ? fmt(selection.calendar.celdas.reduce((s, c) => s + (c.celdas_dia || 0), 0)) : '…'}</b></article>
          <article><span>{tr('metric.modisViirs')}</span><b>{selection?.calendar ? `${fmt(selection.calendar.celdas.reduce((s, c) => s + (c.focos_modis || 0), 0))} / ${fmt(selection.calendar.celdas.reduce((s, c) => s + (c.focos_viirs || 0), 0))}` : '…'}</b></article>
          <article><span>{tr('sel.onMap')}</span><b>{selection?.focos ? fmt(selection.focos.n_focos) : '…'}</b></article>
          <article><span>{tr('sel.boxArea')}</span><b>{selectionArea >= 1000 ? tr('sel.thousandKm2', { v: fmt(selectionArea / 1000, 1) }) : `${fmt(selectionArea)} km²`}</b></article>
          <article><span>{tr('sel.monthAnomaly')}</span><b>{selected.month && selection?.calendar ? (selection.calendar.celdas[0]?.categoria ? catLabel(selection.calendar.celdas[0].categoria) : '–') : tr('sel.pickMonth')}</b></article>
        </div>}
        <div className="fw-selection-actions"><button onClick={toggleSelectionMode}><Scan size={15}/>{tr('sel.redraw')}</button><button onClick={() => selection?.bbox && runDownload(selection.bbox, tr('csv.area'))} disabled={!selection?.calendar}><Download size={15}/>CSV</button><button onClick={() => selection?.bbox && openReport(informeUrl(selection.bbox, reportExtra))} disabled={!selection?.calendar} title={tr('report.tip')}><FileText size={15}/>{tr('report.short')}</button></div>
      </aside>}
      {simpleOpen && (NK
        ? <PanelHistoria key={lang} aoi={selection?.bbox || aoi} etiqueta={selection?.bbox ? 'area' : 'cusco'}/>
        : <SimplePanel key={lang} aoi={selection?.bbox || aoi} etiqueta={selection?.bbox ? 'area' : 'cusco'} onClose={() => setSimpleOpen(false)}/>)}
      {ambitosOpen && !liveOn && <AmbitosPanel key={lang} map={mapRef.current} seleccion={{ year: selected.year, month: selected.month, day: selected.day, custom: Boolean(customPeriod) }} onClose={() => setAmbitosOpen(false)}/>}
      {compareOpen && <ComparisonWorkspace key={lang} calendar={calendar} region={region} regionName={selectedRegion.name} onClose={() => setCompareOpen(false)}/>}
      {calendarOpen && <CalendarPanel calendar={calendar} mode={calendarMode} setMode={setCalendarMode} selected={selected} onSelect={selectMonth} onClose={() => setCalendarOpen(false)} reportUrl={informeUrl(aoi, reportExtra)}/>}
      {NK ? <SeasonRibbon calendar={calendar} selected={selected} onMonth={selectMonth} firstYear={FIRST_YEAR} lastYear={LAST_YEAR}
        customLabel={customPeriod ? periodo.label : null} playing={playing} onPlay={() => { setCustomPeriod(null); setPlaying((v) => !v) }}
        onYear={(y) => { setPlaying(false); setCustomPeriod(null); setSelected({ year: y, month: null }) }} onShiftYear={shiftYear}
        dias={diasMes} onDay={elegirDia} onShiftMonth={shiftMonth}
        onAllYear={() => { setCustomPeriod(null); setSelected((st) => ({ year: st.year, month: null })); setPlaying(false) }}/> : <>
      <section className="fw-timeline fc-timeline">
        <button className="fw-play" onClick={() => { setCustomPeriod(null); setPlaying((v) => !v) }} title={playing ? tr('timeline.pause') : tr('timeline.play')}>{playing ? <Pause size={19}/> : <Play size={19}/>}</button>
        <div className="fw-timeline-panel" style={{ '--progress': `${selected.month ? ((selected.month - 1) / 11) * 100 : 100}%` }}>
          <div className={`fw-time-callout ${selected.month === 1 ? 'is-start' : !selected.month || selected.month === 12 ? 'is-end' : ''}`}><b>{periodo.label}</b><span>{tr('timeline.yearSum', { n: fmtFocos(selected.month ? (month?.focos_armonizados ?? 0) : yearTotal) })}</span></div>
          <div className="fw-days">
            {MESES.map((label, idx) => {
              const c = yearCells.find((x) => x.mes === idx + 1)
              const noData = !c || c.sin_dato
              return <button key={label} disabled={noData} className={[selected.month === idx + 1 ? 'is-active' : '', c?.calidad === 'extrapolado' ? 'is-extrap' : ''].join(' ')} onClick={() => selectMonth(selected.year, idx + 1)} title={noData ? tr('noData') : tr('popup.weight', { v: fmt(c.focos_armonizados, 2) })}><span>{label}</span><small>{noData ? '–' : fmtFocos(c.focos_armonizados)}</small><i style={{ width: `${noData ? 0 : Math.round(100 * c.focos_armonizados / yearMax)}%` }}/></button>
            })}
          </div>
          <div className="fw-timeline-options">
            <button className={selected.month === null && !customPeriod ? 'is-active' : ''} title={tr('timeline.allYear')} aria-label={tr('timeline.allYear')} onClick={() => { setCustomPeriod(null); setSelected((s) => ({ year: s.year, month: null })); setPlaying(false) }}><Layers3 size={13}/><span>{tr('timeline.allYear')}</span></button>
            <div className="fw-year-scale" aria-label={tr('timeline.years')}>
              <button className="fc-year" onClick={() => shiftYear(-1)} title={tr('timeline.prevYear')} disabled={selected.year <= FIRST_YEAR}><ChevronLeft size={13}/></button>
              <div className="fc-years" ref={yearsRef}>
                {YEARS.map((y) => <button key={y} aria-label={String(y)} title={String(y)} className={selected.year === y && !customPeriod ? 'is-active' : ''} onClick={() => { setPlaying(false); setCustomPeriod(null); setSelected({ year: y, month: null }) }}>{String(y).slice(2)}</button>)}
              </div>
              <button className="fc-year" onClick={() => shiftYear(1)} title={tr('timeline.nextYear')} disabled={selected.year >= LAST_YEAR}><ChevronRight size={13}/></button>
            </div>
            <div className="fw-timeline-source"><span>NASA FIRMS · UTC−5</span><b title={latency ? `${latency} ms` : undefined}>{tr('timeline.historic')}</b></div>
          </div>
        </div>
      </section>
      </>}
      <TutorialGuide lang={lang} prompt={tutorialPrompt} open={tutorialOpen} onStart={startTutorial} onSkip={closeTutorial} onClose={closeTutorial} areaRect={cuscoRect} onStep={pasoTutorial}/>
      {snake && <NikalSnake origen={snake} onClose={() => setSnake(null)}/>}
    </div>
  )
}

export default FireMapApp
