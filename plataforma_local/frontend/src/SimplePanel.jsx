// Panel "En simple": cinco preguntas con su respuesta en una frase y cuatro gráficos
// descargables (PNG y CSV). Datos: /api/resumen y /api/analitica/* del backend.
import { useEffect, useState } from 'react'
import { Download, X } from 'lucide-react'
import * as Charts from './charts.js'
import { getAnalitica, getResumen } from './services/api.js'
import { tr } from './i18n.js'

const GRAFICOS = [
  ['estacionalidad', 'meses'], ['ranking', 'anios'], ['acumulado', 'curva-del-anio'], ['altitud', 'altitud'],
]

function Grafico({ tipo, slug, datos, etiqueta, anios, onAnio }) {
  const { svg, csv } = Charts[tipo](datos)
  const nombre = `nikal_${etiqueta}_${slug}${tipo === 'acumulado' ? `_${datos.anio}` : ''}`
  return (
    <article className="fs-chart">
      <header>
        <h3>{datos.titulo}</h3>
        {tipo === 'acumulado' && <select aria-label={tr('simple.year')} value={datos.anio} onChange={(e) => onAnio(e.target.value)}>{anios.map((a) => <option key={a}>{a}</option>)}</select>}
      </header>
      {/* El SVG se arma en charts.js solo con números y textos de nuestra API. */}
      <div className="fs-svg" dangerouslySetInnerHTML={{ __html: svg }}/>
      <p className="fs-answer">{datos.en_simple}</p>
      <p className="fs-how">{datos.como_leerlo}</p>
      <div className="fs-actions">
        <button onClick={() => Charts.downloadPng(svg, `${nombre}.png`)}><Download size={13}/>PNG</button>
        <button onClick={() => Charts.downloadCsv(csv, `${nombre}.csv`)}><Download size={13}/>{tr('simple.data')}</button>
      </div>
    </article>
  )
}

function SimplePanel({ aoi, etiqueta, onClose }) {
  const [estado, setEstado] = useState({ cargando: true })
  const clave = JSON.stringify(aoi)

  useEffect(() => {
    let activo = true
    setEstado({ cargando: true })                 // al cambiar de área, no mostrar la anterior
    const area = JSON.parse(clave)
    // Una sola llamada: frases + datos de los 4 gráficos (antes 5 llamadas y cálculos repetidos).
    getResumen(area, { graficos: 'true' })
      .then(({ body }) => activo && setEstado({ resumen: body, graficos: GRAFICOS.map(([tipo]) => body.graficos[tipo]) }))
      .catch((e) => activo && setEstado({ error: e.message }))
    return () => { activo = false }
  }, [clave])

  const cambiarAnio = (anio) => {
    getAnalitica('acumulado', JSON.parse(clave), { anio })
      .then(({ body }) => setEstado((s) => ({ ...s, graficos: s.graficos.map((g, i) => (i === 2 ? body : g)) })))
      .catch((e) => setEstado((s) => ({ ...s, error: e.message })))
  }

  const { resumen, graficos, error, cargando } = estado
  const anios = graficos ? graficos[1].anios.map((a) => a.anio).sort((a, b) => b - a) : []
  return (
    <aside className="fs-panel" aria-label="El fuego en simple">
      <div className="fs-head">
        <div><p>{tr('simple.kicker')}</p><h2>{resumen?.titulo || tr('simple.title')}</h2></div>
        <button onClick={onClose} title={tr('btn.close')}><X size={16}/></button>
      </div>
      <div className="fs-body">
        {cargando && <p className="fs-how">{tr('simple.loading')}</p>}
        {error && <p className="fs-error">{error}</p>}
        {resumen && <dl className="fs-frases">{resumen.frases.map((f) => <div key={f.pregunta}><dt>{f.pregunta}</dt><dd>{f.respuesta}</dd></div>)}</dl>}
        {graficos && <div className="fs-charts">{GRAFICOS.map(([tipo, slug], i) => <Grafico key={tipo} tipo={tipo} slug={slug} datos={graficos[i]} etiqueta={etiqueta} anios={anios} onAnio={cambiarAnio}/>)}</div>}
      </div>
    </aside>
  )
}

export default SimplePanel
