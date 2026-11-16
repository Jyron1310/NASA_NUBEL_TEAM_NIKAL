// Focos de calor por día del año según el nivel de peligro (CENEPRED) de la unidad donde ocurren.
// Datos: GET /api/ambitos/{nivel}/dias (curva) y /api/ambitos/{nivel}/dias/{dia} (celdas del día para el
// mapa); ambos se calculan al pedirlos con los años y la ventana de suavizado elegidos.
// Áreas apiladas por nivel (colores de datos de CENEPRED, los mismos del mapa y la lista). El día elegido
// (clic, ◀ ▶ o ▶ reproducir) se refleja en el mapa: se ven solo los focos de esos días. La barra inferior manda:
// su año fija los años del gráfico, su mes se marca en el gráfico y su día se fija (ventana de 1 día), así el
// mapa muestra la distribución por nivel de peligro de la fecha elegida en la cinta.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Pause, Play, X } from 'lucide-react'
import { getAmbitoDia, getAmbitoDias } from './services/api.js'
import { locale, monthLetters, tr } from './i18n.js'

const ANIOS = Array.from({ length: 2025 - 2003 + 1 }, (_, i) => 2003 + i)
const W = 380, H = 170, M = { l: 30, r: 8, t: 8, b: 20 }
const INICIO_MES = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
const n1 = (v) => (v >= 10 ? Math.round(v) : Math.round(v * 10) / 10).toLocaleString(locale())
const fechaCorta = (dia) => new Date(2001, 0, dia).toLocaleDateString(locale(), { day: 'numeric', month: 'long' })
const OCULTAR = ['fire-heat', 'fire-points']   // capas del periodo general mientras se ve un día
const REF = [2003, 2025]                         // años de la tipificación (completos, sin extrapolados)
// Día 1-365 sin bisiestos (el 29 de febrero cuenta como el 28), igual que el backend.
function diaDelAnio(y, m, d) {
  const n = Math.round((Date.UTC(y, m - 1, d) - Date.UTC(y, 0, 1)) / 864e5) + 1
  const bis = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0
  return bis && (m > 2 || (m === 2 && d === 29)) ? n - 1 : n
}

// ---------- capa del día en el mapa ----------
function pintarDia(map, geojson) {
  if (!map) return
  if (!map.isStyleLoaded()) { map.once('idle', () => pintarDia(map, geojson)); return }
  const max = Math.max(0.05, ...geojson.features.map((f) => f.properties.n))
  const peso = ['min', 1, ['/', ['get', 'n'], max]]
  if (!map.getSource('ambito-dia')) {
    map.addSource('ambito-dia', { type: 'geojson', data: geojson })
    map.addLayer({ id: 'ambito-dia-heat', type: 'heatmap', source: 'ambito-dia', maxzoom: 11, paint: {
      'heatmap-weight': peso, 'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 5, 0.9, 9, 1.6],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 5, 9, 8, 18, 11, 30], 'heatmap-opacity': 0.9,
      'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(252,165,10,0)', 0.2, 'rgba(252,165,10,.35)',
        0.45, '#fca50a', 0.7, '#dd513a', 0.9, '#b5367a', 1, '#5c1a52'] } })
    map.addLayer({ id: 'ambito-dia-pts', type: 'circle', source: 'ambito-dia', minzoom: 8, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 2.5, 12, 6], 'circle-color': '#fcffa4',
      'circle-stroke-color': '#141210', 'circle-stroke-width': 1, 'circle-opacity': 0.9 } })
  } else {
    map.getSource('ambito-dia').setData(geojson)
    map.setPaintProperty('ambito-dia-heat', 'heatmap-weight', peso)
  }
  ;['ambito-dia-heat', 'ambito-dia-pts'].forEach((id) => map.setLayoutProperty(id, 'visibility', 'visible'))
}

function AmbitosDias({ nivel, map, seleccion }) {
  const [desde, setDesde] = useState(2003)
  const [hasta, setHasta] = useState(2025)
  const [ventana, setVentana] = useState(7)
  const [modo, setModo] = useState('focos')
  const [estado, setEstado] = useState({ cargando: true })
  const [dia, setDia] = useState(null)            // cursor (solo el gráfico)
  const [fijo, setFijo] = useState(null)          // día elegido: se refleja en el mapa
  const [delDia, setDelDia] = useState(null)
  const [jugando, setJugando] = useState(false)
  const previo = useRef(null)

  useEffect(() => {
    let activo = true
    setEstado((s) => ({ ...s, cargando: true, error: '' }))
    getAmbitoDias(nivel, { desde, hasta, ventana })
      .then(({ body }) => {
        if (!activo) return
        setEstado({ d: body })
      })
      .catch((e) => activo && setEstado({ error: e.message }))
    return () => { activo = false }
  }, [nivel, desde, hasta, ventana])

  // El día elegido (o los años, la ventana o el ámbito) cambia el mapa.
  useEffect(() => {
    if (!map || !fijo) return undefined
    let activo = true
    const id = setTimeout(() => {
      getAmbitoDia(nivel, fijo, { desde, hasta, ventana })
        .then(({ body }) => {
          if (!activo) return
          setDelDia(body)
          if (!previo.current) previo.current = OCULTAR.filter((l) => map.getLayer(l)).map((l) => [l, map.getLayoutProperty(l, 'visibility') || 'visible'])
          OCULTAR.forEach((l) => map.getLayer(l) && map.setLayoutProperty(l, 'visibility', 'none'))
          pintarDia(map, body.geojson)
        })
        .catch(() => activo && setDelDia(null))
    }, 180)
    return () => { activo = false; clearTimeout(id) }
  }, [map, nivel, fijo, desde, hasta, ventana])

  // Sin día elegido (o al cerrar el panel): se quita la capa y vuelven los focos del periodo.
  useEffect(() => {
    if (fijo || !map) return undefined
    restaurar(map, previo)
    return undefined
  }, [fijo, map])
  useEffect(() => () => restaurar(map, previo), [map])

  // La cinta inferior manda: su año (si está en 2003-2025) fija los años; su día se fija con ventana de 1 día.
  // Sin día, se suelta el día y el mapa muestra el periodo de la cinta sobre las unidades por nivel de peligro.
  const sy = seleccion?.year, sm = seleccion?.month, sd = seleccion?.day, sc = seleccion?.custom
  useEffect(() => {
    if (sc || !sy) return
    setJugando(false)
    if (sy >= REF[0] && sy <= REF[1]) { setDesde(sy); setHasta(sy) }
    if (sm && sd) { setVentana(1); setFijo(diaDelAnio(sy, sm, sd)) } else { setFijo(null); setDelDia(null) }
  }, [sy, sm, sd, sc])
  const mesRango = sm && !sc ? [diaDelAnio(2001, sm, 1), diaDelAnio(2001, sm, new Date(2001, sm, 0).getDate())] : null

  // ▶ recorre el año avanzando de a una ventana.
  useEffect(() => {
    if (!jugando) return undefined
    const id = setInterval(() => setFijo((f) => ((f || 1) - 1 + Math.max(1, ventana)) % 365 + 1), 900)
    return () => clearInterval(id)
  }, [jugando, ventana])

  const { d, error, cargando } = estado
  const niveles = useMemo(() => (d?.niveles || []).filter((n) => n.focos_por_anio > 0), [d])
  const capas = useMemo(() => {
    if (!d) return []
    const valor = (f, k) => (modo === 'parte' ? (f.total > 0 ? f[k] / f.total : 0) : f[k])
    const max = modo === 'parte' ? 1 : Math.max(1e-9, ...d.dias.map((f) => f.total))
    const x = (i) => M.l + (i / 364) * (W - M.l - M.r)
    const y = (v) => M.t + (1 - v / max) * (H - M.t - M.b)
    let base = d.dias.map(() => 0)
    return { max, x, y, areas: niveles.map((n) => {
      const top = d.dias.map((f, i) => base[i] + valor(f, n.nivel_peligro))
      const path = `${top.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')}`
        + `${base.map((v, i) => [i, v]).reverse().map(([i, v]) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')}Z`
      base = top
      return { n, path }
    }) }
  }, [d, niveles, modo])

  const diaDe = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const fx = ((e.clientX - r.left) / r.width) * W
    return Math.min(365, Math.max(1, Math.round(((fx - M.l) / (W - M.l - M.r)) * 364) + 1))
  }
  const mover = (delta) => { setJugando(false); setFijo((f) => (((f || 1) - 1 + delta) % 365 + 365) % 365 + 1) }
  const fila = d && dia ? d.dias[dia - 1] : null
  const letras = monthLetters()
  const paso = Math.max(1, ventana)

  return (
    <section className="fa-dias" aria-label={tr('amb.days.title')}>
      <header><h3>{tr('amb.days.title')}</h3></header>
      <div className="fa-dias-ctrl">
        <label>{tr('amb.days.from')}<select value={desde} onChange={(e) => { const v = Number(e.target.value); setDesde(v); if (v > hasta) setHasta(v) }}>{ANIOS.map((a) => <option key={a}>{a}</option>)}</select></label>
        <label>{tr('amb.days.to')}<select value={hasta} onChange={(e) => { const v = Number(e.target.value); setHasta(v); if (v < desde) setDesde(v) }}>{ANIOS.map((a) => <option key={a}>{a}</option>)}</select></label>
        <label>{tr('amb.days.window')}<select value={ventana} onChange={(e) => setVentana(Number(e.target.value))}>{(d?.ventanas || [1, 7, 15, 31]).map((v) => <option key={v} value={v}>{tr(v === 1 ? 'amb.days.day1' : 'amb.days.dayN', { n: v })}</option>)}</select></label>
        <span className="fa-dias-modo" role="group" aria-label={tr('amb.days.mode')}>
          {['focos', 'parte'].map((m) => <button key={m} className={modo === m ? 'is-active' : ''} aria-pressed={modo === m} onClick={() => setModo(m)}>{tr(`amb.days.${m}`)}</button>)}
        </span>
      </div>
      {error && <p className="fa-error">{error}</p>}
      {d && <>
        <p className="fa-dias-lead">{d.en_simple}</p>
        <div className={`fa-dias-chart ${cargando ? 'is-loading' : ''}`}>
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${d.titulo}. ${d.en_simple}`}
            onMouseMove={(e) => setDia(diaDe(e))} onMouseLeave={() => setDia(null)} onClick={(e) => { setJugando(false); setFijo(diaDe(e)) }}>
            {[0.5, 1].map((f) => <g key={f}><line x1={M.l} x2={W - M.r} y1={capas.y(capas.max * f)} y2={capas.y(capas.max * f)} className="fa-dias-grid"/>
              <text x={M.l - 4} y={capas.y(capas.max * f) + 3} textAnchor="end" className="fa-dias-eje">{modo === 'parte' ? `${Math.round(100 * f)} %` : n1(capas.max * f)}</text></g>)}
            {mesRango && <rect x={capas.x(mesRango[0] - 1)} width={capas.x(mesRango[1] - 1) - capas.x(mesRango[0] - 1)} y={M.t} height={capas.y(0) - M.t} className="fa-dias-mes"/>}
            {fijo && ventana > 1 && <rect x={capas.x(Math.max(0, fijo - 1 - Math.floor(ventana / 2)))} width={capas.x(Math.min(364, fijo - 1 + Math.floor(ventana / 2))) - capas.x(Math.max(0, fijo - 1 - Math.floor(ventana / 2)))} y={M.t} height={capas.y(0) - M.t} className="fa-dias-ventana"/>}
            {capas.areas.map(({ n, path }) => <path key={n.nivel_peligro} d={path} fill={n.color} fillOpacity=".88"><title>{n.etiqueta}</title></path>)}
            <line x1={M.l} x2={W - M.r} y1={capas.y(0)} y2={capas.y(0)} className="fa-dias-grid"/>
            {INICIO_MES.map((dd, i) => <text key={i} x={capas.x(dd - 1 + 15)} y={H - 6} textAnchor="middle" className="fa-dias-eje">{letras[i]}</text>)}
            {fijo && <line x1={capas.x(fijo - 1)} x2={capas.x(fijo - 1)} y1={M.t} y2={capas.y(0)} className="fa-dias-fijo"/>}
            {fila && <line x1={capas.x(dia - 1)} x2={capas.x(dia - 1)} y1={M.t} y2={capas.y(0)} className="fa-dias-cursor"/>}
          </svg>
          {fila && <div className="fa-dias-tip" style={{ left: `${(100 * capas.x(dia - 1)) / W}%` }}>
            <b>{fechaCorta(dia)}</b>
            {niveles.map((n) => <span key={n.nivel_peligro}><i style={{ background: n.color }}/>{n.etiqueta}: {modo === 'parte' ? `${Math.round(100 * (fila.total ? fila[n.nivel_peligro] / fila.total : 0))} %` : n1(fila[n.nivel_peligro])}</span>)}
          </div>}
        </div>
        <div className="fa-dias-mapa" aria-live="polite">
          <button onClick={() => mover(-paso)} aria-label={tr('amb.days.prev')}><ChevronLeft size={15}/></button>
          <button onClick={() => { if (!fijo) setFijo(1); setJugando((v) => !v) }} aria-label={jugando ? tr('timeline.pause') : tr('amb.days.play')}>{jugando ? <Pause size={14}/> : <Play size={14}/>}</button>
          <button onClick={() => mover(paso)} aria-label={tr('amb.days.next')}><ChevronRight size={15}/></button>
          <div>
            {fijo ? <><b>{tr('amb.days.onMap')} {delDia?.dias || fechaCorta(fijo)}</b>
              {delDia && <span>{tr('amb.days.mapTotal', { n: n1(delDia.total), u: delDia.unidad })}</span>}</>
              : <span>{tr('amb.days.pick')}</span>}
          </div>
          {fijo && <button onClick={() => { setJugando(false); setFijo(null); setDelDia(null) }} aria-label={tr('amb.days.clear')} title={tr('amb.days.clear')}><X size={14}/></button>}
        </div>
        <ul className="fa-dias-niveles">
          {niveles.map((n) => <li key={n.nivel_peligro}>
            <i style={{ background: n.color }}/><b>{n.etiqueta}</b>
            <span>{tr('amb.days.share', { p: Math.round(100 * n.parte), u: n.unidades })}</span>
            <span>{tr('amb.days.peak', { f: n.fecha_pico })}</span>
            <span>{tr('amb.days.central', { r: n.temporada_central })}</span>
          </li>)}
        </ul>
        <p className="fa-note">{d.como_leerlo} {tr('amb.days.unit', { u: d.unidad })}</p>
      </>}
    </section>
  )
}

function restaurar(map, previo) {
  if (!map) return
  ;['ambito-dia-heat', 'ambito-dia-pts'].forEach((id) => map.getLayer?.(id) && map.setLayoutProperty(id, 'visibility', 'none'))
  ;(previo.current || []).forEach(([l, v]) => map.getLayer?.(l) && map.setLayoutProperty(l, 'visibility', v))
  previo.current = null
}

export default AmbitosDias
