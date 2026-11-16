// Panel "Ámbitos": nivel de peligro por focos de calor (formato CENEPRED) por provincia, distrito
// o cuenca Pfafstetter, con el mapa pintado por nivel, la lista ordenada, el informe de cada unidad
// y la tabla CSV del nivel. Datos: /api/ambitos/* del backend.
import { useEffect, useState } from 'react'
import { CalendarDays, Download, Eye, LoaderCircle, X } from 'lucide-react'
import { ambitoUrl, getAmbitoGeojson, getAmbitoNivel, getAmbitos, informeUrl } from './services/api.js'
import { tr } from './i18n.js'
import AmbitosDias from './AmbitosDias.jsx'

const LEVELS = ['muy_alto', 'alto', 'medio', 'bajo', 'sin_clasificar']
const COLORS = { muy_alto: '#c0392b', alto: '#e67e22', medio: '#f1c40f', bajo: '#27ae60', sin_clasificar: '#98a2b3' }

function paint(map, geojson) {
  if (!map) return
  // Si el mapa todavía carga su estilo, se pinta apenas termine (si no, la capa no aparecería).
  if (!map.isStyleLoaded()) { map.once('idle', () => paint(map, geojson)); return }
  if (!map.getSource('ambitos')) {
    map.addSource('ambitos', { type: 'geojson', data: geojson })
    const before = map.getLayer('fire-heat') ? 'fire-heat' : undefined
    map.addLayer({ id: 'ambitos-fill', type: 'fill', source: 'ambitos', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.5 } }, before)
    map.addLayer({ id: 'ambitos-line', type: 'line', source: 'ambitos', paint: { 'line-color': '#1d2330', 'line-width': 0.7, 'line-opacity': 0.75 } }, before)
  } else {
    map.getSource('ambitos').setData(geojson)
  }
  map.setLayoutProperty('ambitos-fill', 'visibility', 'visible')
  map.setLayoutProperty('ambitos-line', 'visibility', 'visible')
}

function hide(map) {
  if (map?.getLayer?.('ambitos-fill')) {
    map.setLayoutProperty('ambitos-fill', 'visibility', 'none')
    map.setLayoutProperty('ambitos-line', 'visibility', 'none')
  }
}

async function captureReportMap(map, codigo) {
  if (!map?.getCanvas?.()) return ''
  const pointsLayer = map.getLayer('fire-points') ? map.getLayoutProperty('fire-points', 'visibility') : null
  const fillFilter = map.getLayer('ambitos-fill') ? map.getFilter('ambitos-fill') : null
  const lineFilter = map.getLayer('ambitos-line') ? map.getFilter('ambitos-line') : null
  try {
    if (map.getLayer('fire-points')) map.setLayoutProperty('fire-points', 'visibility', 'visible')
    if (codigo && map.getLayer('ambitos-fill')) map.setFilter('ambitos-fill', ['==', ['get', 'codigo'], codigo])
    if (codigo && map.getLayer('ambitos-line')) map.setFilter('ambitos-line', ['==', ['get', 'codigo'], codigo])
    await new Promise((resolve) => {
      let finished = false
      const done = () => { if (!finished) { finished = true; resolve() } }
      map.once('render', done); map.triggerRepaint(); window.setTimeout(done, 500)
    })
    return map.getCanvas().toDataURL('image/jpeg', 0.9)
  } finally {
    if (map.getLayer('fire-points')) map.setLayoutProperty('fire-points', 'visibility', pointsLayer || 'none')
    if (map.getLayer('ambitos-fill')) map.setFilter('ambitos-fill', fillFilter || null)
    if (map.getLayer('ambitos-line')) map.setFilter('ambitos-line', lineFilter || null)
    map.triggerRepaint()
  }
}

function addMapToReport(html, image, caption) {
  if (!image) return html
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const style = doc.createElement('style')
  style.textContent = '.fc-report-summary{display:grid;grid-template-columns:minmax(0,.86fr) minmax(280px,1.14fr);gap:18px;align-items:start}.fc-report-summary>p{margin-top:0}.fc-report-map{margin:0;border:1px solid #cdd9df;background:#f4f7f8;break-inside:avoid}.fc-report-map img{display:block;width:100%;aspect-ratio:16/10;object-fit:cover}.fc-report-map figcaption{padding:7px 9px;color:#526671;font-size:9px}@media(max-width:720px){.fc-report-summary{grid-template-columns:1fr}}'
  doc.head.append(style)
  const summary = doc.querySelector('h2')?.nextElementSibling
  if (summary) {
    const grid = doc.createElement('div'); grid.className = 'fc-report-summary'
    const figure = doc.createElement('figure'); figure.className = 'fc-report-map'
    const img = doc.createElement('img'); img.src = image; img.alt = caption
    const figcaption = doc.createElement('figcaption'); figcaption.textContent = caption
    figure.append(img, figcaption); summary.replaceWith(grid); grid.append(summary, figure)
  }
  return `<!doctype html>${doc.documentElement.outerHTML}`
}

async function downloadReportPdf(html, filename) {
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.style.cssText = 'position:fixed;left:-12000px;top:0;width:1000px;height:1400px;border:0;opacity:0;pointer-events:none'
  document.body.append(frame)
  try {
    const doc = frame.contentDocument; doc.open(); doc.write(html); doc.close()
    await new Promise((resolve) => window.setTimeout(resolve, 350))
    if (doc.fonts?.ready) await doc.fonts.ready
    const module = await import('html2pdf.js'); const html2pdf = module.default || module
    await html2pdf().set({ margin: [8, 8, 8, 8], filename, image: { type: 'jpeg', quality: 0.95 }, html2canvas: { scale: 1.45, useCORS: true, logging: false, windowWidth: 1000 }, jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }, pagebreak: { mode: ['css', 'legacy'] } }).from(doc.body).save()
  } finally { frame.remove() }
}

function AmbitosPanel({ map, onClose, seleccion }) {
  const [niveles, setNiveles] = useState([])
  const [nivel, setNivel] = useState('provincia')
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState('')
  const [elegido, setElegido] = useState(null)
  const [fechaInicio, setFechaInicio] = useState('2000-11-01')
  const [fechaFin, setFechaFin] = useState('2025-12-31')
  const [reportLoading, setReportLoading] = useState('')

  useEffect(() => {
    getAmbitos().then(({ body }) => setNiveles(body.niveles)).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    let activo = true
    setDatos(null)
    setError('')
    setElegido(null)
    Promise.all([getAmbitoNivel(nivel), getAmbitoGeojson(nivel)])
      .then(([a, g]) => {
        if (!activo) return
        setDatos(a.body)
        paint(map, g.body)
      })
      .catch((e) => activo && setError(e.message))
    return () => { activo = false }
  }, [nivel, map])

  // Clic en una unidad del mapa: se elige en la lista.
  useEffect(() => {
    if (!map) return undefined
    const onClick = (ev) => {
      const p = ev.features?.[0]?.properties
      if (p?.codigo) setElegido(String(p.codigo))
    }
    const enter = () => { map.getCanvas().style.cursor = 'pointer' }
    const leave = () => { map.getCanvas().style.cursor = '' }
    map.on('click', 'ambitos-fill', onClick)
    map.on('mouseenter', 'ambitos-fill', enter)
    map.on('mouseleave', 'ambitos-fill', leave)
    return () => {
      map.off('click', 'ambitos-fill', onClick)
      map.off('mouseenter', 'ambitos-fill', enter)
      map.off('mouseleave', 'ambitos-fill', leave)
      hide(map)
    }
  }, [map])

  const politicos = niveles.filter((n) => n.grupo === 'politico')
  const hidro = niveles.filter((n) => n.grupo === 'hidrografico')
  const conteo = datos?.conteo || {}
  const periodoValido = Boolean(fechaInicio && fechaFin && fechaInicio <= fechaFin)
  const inicioMes = fechaInicio.slice(0, 7)
  const finMes = fechaFin.slice(0, 7)
  const unidadElegida = datos?.unidades?.find((u) => u.codigo === elegido)
  const reportUrl = (codigo = elegido) => codigo && periodoValido
    ? informeUrl({ ambito: `${nivel}:${codigo}` }, { fecha_inicio: inicioMes, fecha_fin: finMes })
    : ''

  const openGeneratedReport = async (mode) => {
    const url = reportUrl()
    if (!url || reportLoading) return
    const popup = mode === 'view' ? window.open('', '_blank') : null
    if (mode === 'view' && !popup) { setError(tr('amb.popupBlocked')); return }
    setReportLoading(mode)
    try {
      const [response, mapImage] = await Promise.all([fetch(url), captureReportMap(map, elegido)])
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
      let html = await response.text()
      html = html.replace('<head>', `<head><base href="${window.location.origin}/">`)
      html = addMapToReport(html, mapImage, tr('amb.mapCaption', { u: unidadElegida?.nombre || elegido, a: inicioMes, b: finMes }))
      if (mode === 'pdf') {
        const safeName = (unidadElegida?.nombre || elegido).toLowerCase().replace(/[^a-z0-9]+/gi, '-')
        await downloadReportPdf(html, `nikal-${nivel}-${safeName}-${inicioMes}-${finMes}.pdf`)
      } else { popup.document.open(); popup.document.write(html); popup.document.close() }
    } catch (e) {
      if (popup) { popup.document.open(); popup.document.write(`<p style="font:14px system-ui;padding:24px;color:#9f2424">${tr('amb.reportError')}: ${e.message}</p>`); popup.document.close() }
      else setError(`${tr('amb.reportError')}: ${e.message}`)
    } finally { setReportLoading('') }
  }

  return (
    <aside className="fa-panel" aria-label={tr('amb.title')}>
      <div className="fa-head">
        <div><p>{tr('amb.kicker')}</p><h2>{tr('amb.title')}</h2></div>
        <button onClick={onClose} title={tr('amb.close')} aria-label={tr('amb.close')}><X size={16}/></button>
      </div>
      <div className="fa-controls">
        <label>{tr('amb.scope')}
          <select value={nivel} onChange={(e) => setNivel(e.target.value)}>
            <optgroup label={tr('amb.political')}>{politicos.map((n) => <option key={n.nivel} value={n.nivel}>{n.titulo} ({n.n_unidades})</option>)}</optgroup>
            <optgroup label={tr('amb.hydro')}>{hidro.map((n) => <option key={n.nivel} value={n.nivel}>{n.titulo} ({n.n_unidades})</option>)}</optgroup>
          </select>
        </label>
        <label>{tr('amb.unit')}
          <select value={elegido || ''} disabled={!datos} onChange={(e) => setElegido(e.target.value || null)}>
            <option value="">{tr('amb.chooseUnit')}</option>
            {(datos?.unidades || []).map((u) => <option key={u.codigo} value={u.codigo}>{u.nombre} · {u.codigo}</option>)}
          </select>
        </label>
        <div className="fa-period">
          <strong><CalendarDays size={14}/>{tr('amb.reportPeriod')}</strong>
          <div>
            <label>{tr('filter.from')}<input type="date" min="2000-11-01" max="2025-12-31" value={fechaInicio} onChange={(e) => setFechaInicio(e.target.value)}/></label>
            <label>{tr('filter.to')}<input type="date" min="2000-11-01" max="2025-12-31" value={fechaFin} onChange={(e) => setFechaFin(e.target.value)}/></label>
          </div>
          {!periodoValido && <small className="fa-period-error">{tr('filter.invalid')}</small>}
          <small>{tr('amb.monthResolution')}</small>
          {reportUrl() ? <div className="fa-report-buttons">
            <button type="button" className="fa-btn" disabled={Boolean(reportLoading)} onClick={() => openGeneratedReport('view')}><Eye size={15}/>{tr('amb.viewReport')}</button>
            <button type="button" className="fa-btn fa-report-primary" disabled={Boolean(reportLoading)} onClick={() => openGeneratedReport('pdf')}><Download size={15}/>{tr('amb.downloadPdf')}</button>
          </div> : <small>{tr('amb.chooseReportUnit')}</small>}
          {reportLoading && <div className="fa-report-loading" role="status"><LoaderCircle size={16}/><span>{tr(reportLoading === 'pdf' ? 'amb.preparingPdf' : 'amb.preparingReport')}</span></div>}
        </div>
      </div>
      {error && <p className="fa-error">{error}</p>}
      {!datos && !error && <p className="fa-note">{tr('amb.loading')}</p>}
      {datos && <>
        <div className="fa-legend">
          {LEVELS.filter((l) => l !== 'sin_clasificar' || Object.keys(conteo).length > 4).map((l) => (
            <span key={l}><i style={{ background: COLORS[l] }}/>{tr(`amb.level.${l}`)}</span>
          ))}
        </div>
        <p className="fa-note">{tr('amb.coverage', { p: Math.round((datos.cobertura || 0) * 1000) / 10 })}</p>
        <AmbitosDias nivel={nivel} map={map} seleccion={seleccion}/>
        <div className="fa-actions">
          <a className="fa-btn" href={ambitoUrl(`/api/ambitos/${nivel}.csv`)}><Download size={14}/>{tr('amb.csv')}</a>
          {unidadElegida && <span>{unidadElegida.nombre} · {inicioMes}–{finMes}</span>}
        </div>
        <p className="fa-note">{datos.metodo.notas[0]} {datos.metodo.notas[1]}</p>
        <p className="fa-note">{datos.fuente}</p>
      </>}
    </aside>
  )
}

export default AmbitosPanel
