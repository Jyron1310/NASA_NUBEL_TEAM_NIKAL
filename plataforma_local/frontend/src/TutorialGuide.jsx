import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Compass, X } from 'lucide-react'

const SELECTORS = ['.fw-nubel-brand', '.nk-chapters', '.fw-summary', '.fc-map-menu', '.fc-timeline', '.fw-layers, .fc-map-menu']

const COPY = {
  es: {
    welcome: '¿Quieres conocer la plataforma?', intro: 'En menos de dos minutos aprenderás a explorar datos, periodos, ámbitos y herramientas del mapa.', start: 'Iniciar tutorial', skip: 'Ahora no', back: 'Atrás', next: 'Siguiente', finish: 'Finalizar', close: 'Cerrar tutorial', progress: (n, t) => `Paso ${n} de ${t}`,
    steps: [
      ['Área de estudio', 'El mapa central presenta Cusco y la serie armonizada MODIS + VIIRS. La intensidad muestra densidad de focos, no área quemada.'],
      ['Capítulos de análisis', 'Abre los datos, la explicación en lenguaje simple, la comparación y los ámbitos territoriales.'],
      ['Datos y filtros', 'Selecciona el periodo, revisa indicadores y descarga el calendario, CSV o informe técnico.'],
      ['Herramientas del mapa', 'Controla focos, selección por cuadro, capas, comparación y calendario desde este menú.'],
      ['Línea histórica', 'Recorre días, meses y años para observar cómo cambia la actividad térmica.'],
      ['Capas y leyenda', 'Cambia el fondo cartográfico y usa la escala para interpretar la información visible.'],
    ],
  },
  en: {
    welcome: 'Would you like a guided tour?', intro: 'In under two minutes, learn how to explore data, periods, areas and map tools.', start: 'Start tutorial', skip: 'Not now', back: 'Back', next: 'Next', finish: 'Finish', close: 'Close tutorial', progress: (n, t) => `Step ${n} of ${t}`,
    steps: [
      ['Study area', 'The central map presents Cusco and the harmonized MODIS + VIIRS series. Intensity shows hotspot density, not burned area.'],
      ['Analysis chapters', 'Open data, plain-language findings, comparison and territorial scopes.'],
      ['Data and filters', 'Choose a period, review indicators and download the calendar, CSV or technical report.'],
      ['Map tools', 'Control hotspots, box selection, layers, comparison and calendar from this menu.'],
      ['Historical timeline', 'Move through days, months and years to see how thermal activity changes.'],
      ['Layers and legend', 'Switch the basemap and use the scale to interpret the visible information.'],
    ],
  },
}

const clamp = (v, min, max) => Math.max(min, Math.min(v, max))

export default function TutorialGuide({ lang, prompt, open, onStart, onSkip, onClose }) {
  const c = COPY[lang] || COPY.en
  const [step, setStep] = useState(0)
  const [rect, setRect] = useState(null)
  useEffect(() => {
    if (!open) { setStep(0); setRect(null); return undefined }
    const update = () => {
      const box = document.querySelector(SELECTORS[step])?.getBoundingClientRect()
      setRect(box ? { left: box.left, top: box.top, right: box.right, bottom: box.bottom, width: box.width, height: box.height } : null)
    }
    update(); const timer = window.setTimeout(update, 250); window.addEventListener('resize', update)
    return () => { window.clearTimeout(timer); window.removeEventListener('resize', update) }
  }, [open, step])
  const position = useMemo(() => {
    const width = Math.min(360, window.innerWidth - 28), height = 250, gap = 18
    if (!rect || window.innerWidth < 680) return { left: 14, top: window.innerHeight - height - 14, width }
    if (rect.right + gap + width < window.innerWidth) return { left: rect.right + gap, top: clamp(rect.top, 14, window.innerHeight - height - 14), width }
    return { left: clamp(rect.left - width - gap, 14, window.innerWidth - width - 14), top: clamp(rect.top, 14, window.innerHeight - height - 14), width }
  }, [rect])
  if (prompt) return <div className="nk-tutorial-prompt" role="dialog" aria-modal="true"><article><Compass/><h2>{c.welcome}</h2><p>{c.intro}</p><footer><button onClick={onSkip}>{c.skip}</button><button className="is-primary" onClick={onStart}>{c.start}<ArrowRight/></button></footer></article></div>
  if (!open) return null
  const last = step === c.steps.length - 1
  return <div className="nk-tutorial-tour" role="dialog" aria-modal="true">
    {rect && <div className="nk-tutorial-spot" style={{ left: rect.left - 7, top: rect.top - 7, width: rect.width + 14, height: rect.height + 14 }}/>}
    <article style={position}><header><small>{c.progress(step + 1, c.steps.length)}</small><button onClick={onClose} aria-label={c.close}><X/></button></header><h2>{c.steps[step][0]}</h2><p>{c.steps[step][1]}</p><div className="nk-tutorial-dots">{c.steps.map((_, i) => <i key={i} className={i <= step ? 'is-active' : ''}/>)}</div><footer><button disabled={!step} onClick={() => setStep(step - 1)}><ArrowLeft/>{c.back}</button><button className="is-primary" onClick={() => last ? onClose() : setStep(step + 1)}>{last ? c.finish : c.next}{last ? <Check/> : <ArrowRight/>}</button></footer></article>
  </div>
}
