// Panel "Entender" de Nikal (diseño de PROMPT_PANEL_NIKAL.md, solo la parte de diseño).
// Lectura de lo general a lo accionable: titular con las cifras clave → 1) ¿este año es normal? →
// 2) ¿cuándo empieza la temporada? → 3) ¿dónde se concentra? → contexto (ranking de años).
// Cada gráfico sigue la anatomía de Our World in Data: título que afirma el hallazgo, subtítulo con lo que se
// mide, etiquetas directas (sin leyenda), y al pie la fuente, la nota de lectura (ⓘ) y una sola descarga.
// Todos los números salen de /api/resumen (graficos=true); si falta un dato, su frase no se muestra.
import { useEffect, useRef, useState } from 'react'
import { Download, Info } from 'lucide-react'
import * as Charts from './charts.js'
import { getAnalitica, getResumen } from './services/api.js'
import { getLang, locale, monthLetters, tr } from './i18n.js'

const C = { anio: '#fca50a', habitual: '#bdb7ad', banda: 'rgba(245,243,238,.11)', rejilla: 'rgba(245,243,238,.09)',
  texto: '#f5f3ee', texto2: '#a8a297', temporada: '#dd513a', resto: '#4d4749', fondo: '#121011', chispa: '#fcffa4' }
const FUENTE = "'Nikal Grotesk', system-ui, sans-serif"
const n0 = (v) => Math.round(v).toLocaleString(locale())
const ordinal = (k) => {
  if (getLang() === 'es') return `${k}.º`
  const s = k % 100 >= 11 && k % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[k % 10] || 'th'
  return `${k}${s}`
}
// Frase con cifras resaltadas: las partes {x} de la plantilla se pintan como <b>.
function Resaltado({ texto }) {
  return texto.split(/(\[[^\]]+\])/g).map((p, i) => (p.startsWith('[') ? <b key={i}>{p.slice(1, -1)}</b> : p))
}

// ---------- descargas: el SVG que se ve (con fondo) a PNG, y los datos a CSV ----------
function svgTexto(svg) {
  const c = svg.cloneNode(true)
  c.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  return new XMLSerializer().serializeToString(c)
}
function bajarPng(svg, nombre) {
  const vb = svg.viewBox.baseVal, img = new Image()
  const url = URL.createObjectURL(new Blob([svgTexto(svg)], { type: 'image/svg+xml;charset=utf-8' }))
  img.onload = () => {
    const cv = document.createElement('canvas')
    cv.width = vb.width * 2; cv.height = vb.height * 2
    cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height)
    URL.revokeObjectURL(url)
    cv.toBlob((b) => { const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = nombre; a.click() }, 'image/png')
  }
  img.src = url
}

function Pie({ nota, nombre, csv, svgRef }) {
  const [info, setInfo] = useState(false)
  const [menu, setMenu] = useState(false)
  return (
    <footer className="ph-pie">
      <span>{tr('ph.source')}</span>
      <button className="ph-ico" aria-label={tr('ph.howToRead')} aria-expanded={info} onClick={() => { setInfo((v) => !v); setMenu(false) }}><Info size={15}/></button>
      <span className="ph-menu">
        <button className="ph-ico" aria-label={tr('ph.download')} aria-expanded={menu} onClick={() => { setMenu((v) => !v); setInfo(false) }}><Download size={15}/></button>
        {menu && <span className="ph-menu-list" role="menu">
          <button role="menuitem" onClick={() => { svgRef.current && bajarPng(svgRef.current, `${nombre}.png`); setMenu(false) }}>{tr('ph.png')}</button>
          <button role="menuitem" onClick={() => { Charts.downloadCsv(csv, `${nombre}.csv`); setMenu(false) }}>{tr('ph.csv')}</button>
        </span>}
      </span>
      {info && <p className="ph-nota" role="note">{nota} {tr('ph.notForecast')}</p>}
    </footer>
  )
}

function Capitulo({ titulo, subtitulo, extra, children, pie, chico }) {
  return (
    <section className={`ph-cap ${chico ? 'is-chico' : ''}`}>
      <header><div><h3>{titulo}</h3>{subtitulo && <p>{subtitulo}</p>}</div>{extra}</header>
      {children}
      {pie}
    </section>
  )
}

// ---------- 1. ¿Este año es normal? (curva acumulada) ----------
function Acumulado({ d, svgRef, desc }) {
  const W = 440, H = 200, M = { l: 34, r: 92, t: 10, b: 22 }
  const max = Math.max(1, ...d.curva.map((p) => Math.max(p.alto, p.acumulado)))
  const x = (dia) => M.l + ((dia - 1) / 364) * (W - M.l - M.r)
  const y = (v) => M.t + (1 - v / max) * (H - M.t - M.b)
  const linea = (k) => d.curva.map((p, i) => `${i ? 'L' : 'M'}${x(p.dia).toFixed(1)},${y(p[k]).toFixed(1)}`).join('')
  const banda = `${linea('alto')}${[...d.curva].reverse().map((p) => `L${x(p.dia).toFixed(1)},${y(p.bajo).toFixed(1)}`).join('')}Z`
  const ult = d.curva[d.curva.length - 1]
  const incompleto = ult.dia < 360
  let ya = y(ult.acumulado), yh = y(ult.normal)
  if (Math.abs(ya - yh) < 24) { if (ya <= yh) { ya -= (24 - (yh - ya)) / 2; yh = ya + 24 } else { yh -= (24 - (ya - yh)) / 2; ya = yh + 24 } }
  const letras = monthLetters()
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={desc} className="ph-svg" fontFamily={FUENTE}>
      <rect width={W} height={H} fill={C.fondo}/>
      {[0.5, 1].map((f) => <g key={f}><line x1={M.l} x2={W - M.r} y1={y(max * f)} y2={y(max * f)} stroke={C.rejilla}/><text x={M.l - 6} y={y(max * f) + 4} textAnchor="end" fill={C.texto2} fontSize="10">{n0(max * f)}</text></g>)}
      <line x1={M.l} x2={W - M.r} y1={y(0)} y2={y(0)} stroke={C.rejilla}/>
      {letras.map((l, i) => <text key={i} x={x(1 + i * 30.4 + 15)} y={H - 6} textAnchor="middle" fill={C.texto2} fontSize="10">{l}</text>)}
      <path d={banda} fill={C.banda}/>
      <path d={linea('normal')} fill="none" stroke={C.habitual} strokeWidth="1.6" strokeDasharray="4 4"/>
      <path d={linea('acumulado')} fill="none" stroke={C.anio} strokeWidth="2.8" strokeLinejoin="round"/>
      <circle cx={x(ult.dia)} cy={y(ult.acumulado)} r="3.5" fill={C.anio}/>
      {incompleto && <text x={x(ult.dia)} y={y(ult.acumulado) - 9} textAnchor="middle" fill={C.anio} fontSize="10">{tr('ph.today')}</text>}
      <text x={W - M.r + 8} y={ya + 4} fill={C.anio} fontSize="12" fontWeight="700">{d.anio} · {n0(d.total)}</text>
      <text x={W - M.r + 8} y={yh + 4} fill={C.habitual} fontSize="11">{tr('ph.usual')} · {n0(d.normal)}</text>
    </svg>
  )
}

// ---------- 2. ¿Cuándo empieza la temporada? (mediana por mes) ----------
function Estacionalidad({ d, prev, svgRef, desc }) {
  const W = 440, H = 170, M = { l: 8, r: 8, t: 26, b: 22 }
  const max = Math.max(1, ...d.meses.map((m) => m.mediana))
  const bw = (W - M.l - M.r) / 12
  const y = (v) => M.t + (1 - v / max) * (H - M.t - M.b)
  const letras = monthLetters()
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={desc} className="ph-svg" fontFamily={FUENTE}>
      <rect width={W} height={H} fill={C.fondo}/>
      <line x1={M.l} x2={W - M.r} y1={y(0)} y2={y(0)} stroke={C.rejilla}/>
      {d.meses.map((m, i) => {
        const x0 = M.l + i * bw + 5, w = bw - 10, top = y(m.mediana)
        const pico = m.mes === d.mes_pico, esPrev = m.mes === prev
        return <g key={m.mes}>
          {esPrev && <rect x={x0 - 3} y={M.t - 4} width={w + 6} height={y(0) - M.t + 4} rx="4" fill="none" stroke={C.chispa} strokeDasharray="3 3"/>}
          <rect x={x0} y={top} width={w} height={Math.max(1.5, y(0) - top)} rx="2" fill={m.en_temporada ? C.temporada : C.resto}><title>{tr('chart.monthTip', { m: m.nombre, v: n0(m.mediana), a: n0(m.p25), b: n0(m.p75) })}</title></rect>
          {pico && <text x={x0 + w / 2} y={top - 6} textAnchor="middle" fill={C.texto} fontSize="11" fontWeight="700">{n0(m.mediana)}</text>}
          {esPrev && <text x={x0 + w / 2} y={M.t - 9} textAnchor="middle" fill={C.chispa} fontSize="10">{tr('ph.getReady')}</text>}
          <text x={x0 + w / 2} y={H - 6} textAnchor="middle" fill={m.en_temporada ? C.texto : C.texto2} fontSize="10">{letras[i]}</text>
        </g>
      })}
    </svg>
  )
}

// ---------- 3. ¿Dónde se concentra? (franjas de altitud, ordenadas) ----------
function Altitud({ d, svgRef, desc }) {
  const filas = [...d.bandas].sort((a, b) => b.parte - a.parte)
  const W = 440, fila = 30, H = filas.length * fila + 8, x0 = 132, xMax = W - 52
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={desc} className="ph-svg" fontFamily={FUENTE}>
      <rect width={W} height={H} fill={C.fondo}/>
      {filas.map((b, i) => {
        const yy = 4 + i * fila, w = Math.max(2, (b.parte / filas[0].parte) * (xMax - x0))
        return <g key={b.banda}>
          <text x={x0 - 10} y={yy + fila / 2 + 4} textAnchor="end" fill={i === 0 ? C.texto : C.texto2} fontSize="11">{b.banda}</text>
          <rect x={x0} y={yy + 6} width={w} height={fila - 12} rx="2" fill={i === 0 ? C.temporada : C.resto}/>
          <text x={x0 + w + 7} y={yy + fila / 2 + 4} fill={i === 0 ? C.texto : C.texto2} fontSize="11" fontWeight={i === 0 ? 700 : 400}>{Math.round(b.parte * 100)} %</text>
        </g>
      })}
    </svg>
  )
}

// ---------- Contexto: los años ordenados en el tiempo, con el año elegido resaltado ----------
function Ranking({ d, anio, svgRef, desc }) {
  const anios = [...d.anios].sort((a, b) => a.anio - b.anio)
  const W = 440, H = 74, M = { l: 6, r: 70, t: 6, b: 16 }
  const max = Math.max(1, ...anios.map((a) => a.total))
  const bw = (W - M.l - M.r) / anios.length
  const y = (v) => M.t + (1 - v / max) * (H - M.t - M.b)
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={desc} className="ph-svg" fontFamily={FUENTE}>
      <rect width={W} height={H} fill={C.fondo}/>
      {anios.map((a, i) => <rect key={a.anio} x={M.l + i * bw + 1.5} y={y(a.total)} width={bw - 3} height={y(0) - y(a.total)} rx="1.5" fill={a.anio === anio ? C.anio : C.resto}><title>{`${a.anio}: ${n0(a.total)}`}</title></rect>)}
      <line x1={M.l} x2={W - M.r} y1={y(d.anio_tipico)} y2={y(d.anio_tipico)} stroke={C.habitual} strokeDasharray="4 4"/>
      <text x={W - M.r + 6} y={y(d.anio_tipico) + 4} fill={C.habitual} fontSize="10">{tr('ph.typical')} · {n0(d.anio_tipico)}</text>
      <text x={M.l} y={H - 3} fill={C.texto2} fontSize="10">{anios[0].anio}</text>
      <text x={W - M.r} y={H - 3} textAnchor="end" fill={C.texto2} fontSize="10">{anios[anios.length - 1].anio}</text>
    </svg>
  )
}

function PanelHistoria({ aoi, etiqueta }) {
  const [estado, setEstado] = useState({ cargando: true })
  const clave = JSON.stringify(aoi)
  const refs = { acu: useRef(null), est: useRef(null), alt: useRef(null), ran: useRef(null) }

  useEffect(() => {
    let activo = true
    setEstado({ cargando: true })
    getResumen(JSON.parse(clave), { graficos: 'true' })
      .then(({ body }) => activo && setEstado({ r: body, acu: body.graficos.acumulado }))
      .catch((e) => activo && setEstado({ error: e.message }))
    return () => { activo = false }
  }, [clave])

  const cambiarAnio = (anio) => getAnalitica('acumulado', JSON.parse(clave), { anio })
    .then(({ body }) => setEstado((s) => ({ ...s, acu: body })))
    .catch((e) => setEstado((s) => ({ ...s, error: e.message })))

  const { r, acu, error, cargando } = estado
  if (!r) {
    return <aside className="ph-panel" aria-label={tr('ph.aria')} aria-busy={cargando}>
      <div className="ph-body">{cargando && <p className="ph-sub">{tr('simple.loading')}</p>}{error && <p className="ph-error">{error}</p>}</div>
    </aside>
  }

  const g = r.graficos, est = g.estacionalidad, alt = g.altitud, ran = g.ranking
  const nombreMes = (m) => est.meses[m - 1]?.nombre
  const [a0, a1] = est.anios_referencia
  const lugar = r.aoi?.tipo === 'departamento' ? r.aoi.descripcion : tr('ph.thisArea')
  const pocos = Math.max(...est.meses.map((m) => m.mediana)) < 0.5      // misma regla que el backend
  const temporada = est.temporada || []
  const seguidos = temporada.length > 1 && temporada.every((m, i) => i === 0 || m === temporada[i - 1] + 1)
  const inicio = temporada[0], prev = inicio ? (inicio === 1 ? 12 : inicio - 1) : null
  const ultimo = acu.curva[acu.curva.length - 1]
  const incompleto = ultimo.dia < 360
  const normalRef = incompleto ? ultimo.normal : acu.normal          // año en curso: lo típico a esta fecha

  // Titular (lead): año, total, diferencia con un año típico y temporada.
  const pct = normalRef > 0 ? Math.round(100 * (acu.total / normalRef - 1)) : null
  const dif = pct === null ? null : Math.abs(pct) < 5 ? tr('ph.lead.same') : pct < 0 ? tr('ph.lead.less', { p: Math.abs(pct) }) : tr('ph.lead.more', { p: pct })
  const lead1 = dif && tr(incompleto ? 'ph.lead.yearSoFar' : 'ph.lead.year', { y: acu.anio, lugar, n: n0(acu.total), dif, normal: n0(normalRef) })
  const lead2 = !pocos && temporada.length ? (seguidos
    ? tr('ph.lead.season', { a: nombreMes(temporada[0]), b: nombreMes(temporada[temporada.length - 1]), pico: nombreMes(est.mes_pico) })
    : tr('ph.lead.seasonMonths', { meses: temporada.map(nombreMes).join(', '), pico: nombreMes(est.mes_pico) })) : null

  // Títulos-hallazgo.
  const veredicto = { 'muy por encima de lo normal': 'above', 'muy por debajo de lo normal': 'below', 'dentro de lo normal': 'within' }[acu.veredicto]
  const t1 = veredicto ? tr(`ph.c1.${veredicto}${incompleto ? '.soFar' : ''}`, { y: acu.anio }) : String(acu.anio)
  const t2 = pocos || !inicio ? tr('ph.c2.few') : tr('ph.c2', { a: nombreMes(inicio), p: nombreMes(prev) })
  const top = [...alt.bandas].sort((a, b) => b.parte - a.parte)[0]
  const parte = top.parte >= 0.45 && top.parte <= 0.55 ? tr('ph.c3.half') : tr('ph.c3.pct', { p: Math.round(top.parte * 100) })
  const t3 = tr('ph.c3', { parte, banda: top.banda })
  const puesto = ran.anios.find((a) => a.anio === acu.anio)?.puesto
  const t4 = puesto ? tr('ph.c4', { y: acu.anio, k: ordinal(puesto), n: ran.anios.length }) : tr('ph.c4.plain')
  const base = `nikal_${etiqueta}`
  const anios = ran.anios.map((a) => a.anio).sort((a, b) => b - a)

  return (
    <aside className="ph-panel" aria-label={tr('ph.aria')}>
      <span className="ph-asa" aria-hidden="true"/>
      <div className="ph-body">
        <h2 className="ph-lugar">{lugar} · {a0}–{a1}</h2>
        {lead1 && <p className="ph-lead"><Resaltado texto={lead1}/>{lead2 && <> <Resaltado texto={lead2}/></>}</p>}
        {pocos && <p className="ph-cautela">{tr('ph.caution')}</p>}

        <Capitulo titulo={t1} subtitulo={tr('ph.c1.sub', { a: a0, b: a1 })}
          extra={<select className="ph-anio" aria-label={tr('simple.year')} value={acu.anio} onChange={(e) => cambiarAnio(e.target.value)}>{anios.map((a) => <option key={a}>{a}</option>)}</select>}
          pie={<Pie nota={acu.como_leerlo} nombre={`${base}_curva-del-anio_${acu.anio}`} csv={Charts.acumulado(acu).csv} svgRef={refs.acu}/>}>
          <Acumulado d={acu} svgRef={refs.acu} desc={`${t1}. ${acu.en_simple}`}/>
        </Capitulo>

        <Capitulo titulo={t2} subtitulo={tr('ph.c2.sub', { a: a0, b: a1 })}
          pie={<Pie nota={est.como_leerlo} nombre={`${base}_meses`} csv={Charts.estacionalidad(est).csv} svgRef={refs.est}/>}>
          <Estacionalidad d={est} prev={pocos ? null : prev} svgRef={refs.est} desc={`${t2}. ${est.en_simple}`}/>
        </Capitulo>

        <Capitulo titulo={t3} subtitulo={tr('ph.c3.sub')}
          pie={<Pie nota={alt.como_leerlo} nombre={`${base}_altitud`} csv={Charts.altitud(alt).csv} svgRef={refs.alt}/>}>
          <Altitud d={alt} svgRef={refs.alt} desc={`${t3}. ${alt.en_simple}`}/>
        </Capitulo>

        <Capitulo chico titulo={t4} subtitulo={tr('ph.c4.sub')}
          pie={<Pie nota={ran.como_leerlo} nombre={`${base}_anios`} csv={Charts.ranking(ran).csv} svgRef={refs.ran}/>}>
          <Ranking d={ran} anio={acu.anio} svgRef={refs.ran} desc={`${t4}. ${ran.en_simple}`}/>
        </Capitulo>
      </div>
    </aside>
  )
}

export default PanelHistoria
