// Vista local "Nikal": barras con criterio narrativo (design thinking + storytelling).
// - ChapterRail: la barra izquierda es un recorrido de 3 capítulos (Mirar → Entender → Actuar); Comparar está
//   en el menú de la derecha.
//   unidos por un hilo; el hilo se "enciende" hasta el capítulo abierto.
// - SeasonRibbon: la barra inferior cuenta la temporada: curva de los 12 meses del año elegido contra lo
//   habitual (mediana del mes), una frase que la resume y la columna de los 26 años debajo. Con un mes
//   elegido pasa a los días de ese mes; año, mes y día cambian lo que muestra el mapa.
// Solo describe lo que ya pasó (no es pronóstico) y usa la unidad "focos armonizados".
import { createElement, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { IcoActuar, IcoEntender, IcoMirar, IcoPausa, IcoPlay } from './NkIcons.jsx'
import { locale, months, tr } from './i18n.js'

const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? '–'
  : Number(v).toLocaleString(locale(), { minimumFractionDigits: d, maximumFractionDigits: d })
const fmtFocos = (v) => (v > 0 && v < 1 ? fmt(v, 1) : fmt(v))

// Años como pila de píxeles (máx. 5), coloreados de abajo hacia arriba con la escala del logo: los años
// con más focos llegan al amarillo pálido de la punta de la llama.
const LLAMA = ['#b5367a', '#dd513a', '#dd513a', '#fca50a', '#fcffa4']
const pixels = (v, max) => (v > 0 ? LLAMA.slice(0, Math.max(1, Math.round((5 * v) / max))) : [])

const CHAPTERS = [
  { id: 'data', icon: IcoMirar },
  { id: 'simple', icon: IcoEntender },
  { id: 'ambitos', icon: IcoActuar },
]

export function ChapterRail({ active, onPick }) {
  const idx = CHAPTERS.findIndex((c) => c.id === active)
  return (
    <nav className="nk-chapters" aria-label={tr('nk.story')} style={{ '--nk-progress': idx < 0 ? 0 : idx / (CHAPTERS.length - 1) }}>
      <span className="nk-thread" aria-hidden="true"><i/></span>
      {CHAPTERS.map((c, i) => (
        <button key={c.id} className={`nk-ch ${active === c.id ? 'is-active' : ''} ${idx > i ? 'is-past' : ''}`}
          aria-pressed={active === c.id} aria-label={`${tr(`nk.ch.${c.id}`)}: ${tr(`nk.ch.${c.id}.sub`)}`} onClick={() => onPick(c.id)}>
          <span className="nk-ch-icon">{createElement(c.icon, { size: 19 })}</span>
          <b>{tr(`nk.ch.${c.id}`)}</b>
          <span className="nk-ch-tip"><b>{tr(`nk.ch.${c.id}`)}</b><small>{tr(`nk.ch.${c.id}.sub`)}</small></span>
        </button>
      ))}
    </nav>
  )
}

// Frase que resume el mes o el año elegido (solo describe; compara con la mediana del mismo mes).
function storyLine({ cell, mesNombre, yearTotal, peak, rank, nYears, year }) {
  if (cell) {
    if (cell.sin_dato) return tr('nk.noData')
    const v = cell.focos_armonizados || 0
    const m = cell.mediana_hist
    if (!m) return v > 0 ? tr('nk.month.rare', { mes: mesNombre }) : tr('nk.month.none', { mes: mesNombre })
    const r = v / m
    if (r >= 1.5) return tr('nk.month.above', { r: fmt(r, 1), mes: mesNombre })
    if (r <= 0.67) return tr('nk.month.below', { p: fmt(100 * r), mes: mesNombre })
    return tr('nk.month.usual', { mes: mesNombre })
  }
  if (!yearTotal) return tr('nk.year.none', { y: year })
  if (!rank) return tr('nk.year.peak', { mes: peak })
  const key = rank <= 5 ? 'nk.year.top' : rank > nYears - 5 ? 'nk.year.low' : 'nk.year.mid'
  return tr(key, { k: rank, n: nYears, mes: peak })
}

export function SeasonRibbon({ calendar, selected, onMonth, onYear, onAllYear, onShiftYear, onShiftMonth, playing, onPlay, firstYear, lastYear, customLabel, dias, onDay }) {
  const MESES = months()
  const [hover, setHover] = useState(null)
  const cells = useMemo(() => calendar?.celdas || [], [calendar])
  const yearCells = useMemo(() => Array.from({ length: 12 }, (_, i) => cells.find((c) => c.anio === selected.year && c.mes === i + 1) || null), [cells, selected.year])
  const totals = useMemo(() => {
    const t = new Map()
    for (const c of cells) t.set(c.anio, (t.get(c.anio) || 0) + (c.focos_armonizados || 0))
    return t
  }, [cells])
  const years = useMemo(() => Array.from({ length: lastYear - firstYear + 1 }, (_, i) => firstYear + i), [firstYear, lastYear])
  const maxYear = Math.max(1, ...years.map((y) => totals.get(y) || 0))

  // Curva: valor del mes y mediana histórica del mismo mes (lo habitual).
  const W = 520, H = 74
  const vmax = Math.max(1, ...yearCells.map((c) => Math.max(c?.focos_armonizados || 0, c?.mediana_hist || 0)))
  const x = (i) => ((i + 0.5) * W) / 12                      // centro de la columna de cada mes
  const y = (v) => H - 4 - (Math.max(0, v) / vmax) * (H - 16)
  const valPts = yearCells.map((c, i) => [x(i), y(c && !c.sin_dato ? c.focos_armonizados || 0 : 0)])
  const smooth = (pts) => pts.reduce((d, [px, py], i) => {
    if (i === 0) return `M${px},${py}`
    const [qx, qy] = pts[i - 1], cx = (qx + px) / 2
    return `${d} C${cx},${qy} ${cx},${py} ${px},${py}`
  }, '')
  const line = smooth(valPts)
  const area = `${line} L${x(11)},${H} L${x(0)},${H} Z`
  const median = smooth(yearCells.map((c, i) => [x(i), y(c?.mediana_hist || 0)]))

  const yearTotal = totals.get(selected.year) || 0
  const full = years.filter((yy) => yy > firstYear)                       // el primer año (2000) está incompleto
  const ranked = [...full].sort((a, b) => (totals.get(b) || 0) - (totals.get(a) || 0))
  const rank = selected.year > firstYear ? ranked.indexOf(selected.year) + 1 : null
  const peakIdx = yearCells.reduce((best, c, i) => ((c?.focos_armonizados || 0) > (yearCells[best]?.focos_armonizados || 0) ? i : best), 0)
  const cell = selected.month ? yearCells[selected.month - 1] : null
  const big = cell ? (cell.sin_dato ? null : cell.focos_armonizados) : yearTotal
  // Vista de días: con un mes elegido, la cinta muestra sus días (suma de focos armonizados por día).
  const vistaDias = Boolean(selected.month && dias && !customLabel)
  const totalMes = vistaDias ? dias.reduce((s, d) => s + d, 0) : 0
  const maxDia = vistaDias ? Math.max(1e-9, ...dias) : 1
  const valorDia = vistaDias && selected.day ? dias[selected.day - 1] || 0 : null
  const kicker = customLabel || (selected.day ? `${selected.day} ${MESES[selected.month - 1]} ${selected.year}` : selected.month ? `${MESES[selected.month - 1]} ${selected.year}` : String(selected.year))
  const sentence = customLabel ? tr('nk.custom')
    : valorDia !== null ? (valorDia > 0 ? tr('nk.day.line', { p: ((q) => fmt(q, q > 0 && q < 1 ? 1 : 0))(totalMes ? (100 * valorDia) / totalMes : 0), mes: MESES[selected.month - 1] }) : tr('nk.day.none'))
    : storyLine({ cell, mesNombre: MESES[(selected.month || 1) - 1], yearTotal, peak: MESES[peakIdx], rank, nYears: full.length, year: selected.year })
  const grande = valorDia !== null ? valorDia : big
  const hv = hover !== null ? yearCells[hover] : null

  return (
    <section className="nk-ribbon fc-timeline" aria-label={tr('nk.season')}>
      <div className="nk-caption">
        <button className="nk-play" onClick={onPlay} title={playing ? tr('timeline.pause') : tr('timeline.play')} aria-label={playing ? tr('timeline.pause') : tr('timeline.play')}>{playing ? <IcoPausa size={16}/> : <IcoPlay size={16}/>}</button>
        <div>
          <p>{kicker}</p>
          <strong>{grande === null ? '–' : fmtFocos(grande)}<small>{tr('nk.unit')}</small></strong>
          <span>{sentence}</span>
        </div>
      </div>

      <div className="nk-season">
        {vistaDias ? <header>
          <span>{MESES[selected.month - 1]} {selected.year} · {tr('nk.days')}</span>
          <span className="nk-legend">{tr('nk.day.hint')}</span>
          <span className="nk-mes-nav">
            <button onClick={() => onShiftMonth(-1)} aria-label={tr('nk.prevMonth')} title={tr('nk.prevMonth')}><ChevronLeft size={13}/></button>
            <button onClick={() => onShiftMonth(1)} aria-label={tr('nk.nextMonth')} title={tr('nk.nextMonth')}><ChevronRight size={13}/></button>
            <button onClick={onAllYear}>{tr('timeline.allYear')}</button>
          </span>
        </header> : <header>
          <span>{tr('nk.season')} {selected.year}</span>
          <span className="nk-legend"><i className="v"/>{tr('nk.legend.value')}<i className="m"/>{tr('nk.legend.usual')}</span>
          <button className={selected.month === null && !customLabel ? 'is-active' : ''} onClick={onAllYear}>{tr('timeline.allYear')}</button>
        </header>}
        {vistaDias ? <div className="nk-dias" style={{ gridTemplateColumns: `repeat(${dias.length}, 1fr)` }}>
          {dias.map((v, i) => <button key={i} className={selected.day === i + 1 ? 'is-active' : ''} onClick={() => onDay(i + 1)}
            aria-pressed={selected.day === i + 1} aria-label={`${i + 1} ${MESES[selected.month - 1]}: ${fmtFocos(v)}`} title={`${i + 1} ${MESES[selected.month - 1]}: ${fmtFocos(v)} ${tr('nk.unit')}`}>
            <i style={{ height: `${v > 0 ? Math.max(6, (100 * v) / maxDia) : 0}%` }}/>
            <span>{i === 0 || (i + 1) % 5 === 0 || selected.day === i + 1 ? i + 1 : ''}</span>
          </button>)}
        </div> : <div className="nk-chart" onMouseLeave={() => setHover(null)}>
          <div className="nk-plot">
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="nk-ember" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fca50a" stopOpacity=".5"/><stop offset=".55" stopColor="#b5367a" stopOpacity=".25"/><stop offset="1" stopColor="#b5367a" stopOpacity="0"/></linearGradient>
            </defs>
            <path d={area} fill="url(#nk-ember)"/>
            <path d={median} className="nk-median" fill="none"/>
            <path d={line} className="nk-line" fill="none"/>
            {selected.month && <line className="nk-cursor" x1={x(selected.month - 1)} x2={x(selected.month - 1)} y1="0" y2={H}/>}
          </svg>
          {selected.month && <span className="nk-dot" style={{ left: `${(100 * x(selected.month - 1)) / W}%`, top: `${(100 * valPts[selected.month - 1][1]) / H}%` }}/>}
          {hv && !hv.sin_dato && <div className="nk-hover" style={{ left: `${(100 * x(hover)) / W}%`, top: `${(100 * valPts[hover][1]) / H}%` }}><b>{fmtFocos(hv.focos_armonizados)}</b><span>{tr('nk.hover.usual', { m: fmt(hv.mediana_hist, 0) })}</span></div>}
          </div>
          <div className="nk-months">
            {MESES.map((m, i) => {
              const c = yearCells[i]
              const noData = !c || c.sin_dato
              return <button key={m} disabled={noData} className={`${selected.month === i + 1 ? 'is-active' : ''} ${c?.calidad === 'extrapolado' ? 'is-extrap' : ''}`}
                onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onClick={() => onMonth(selected.year, i + 1)}
                aria-label={`${m} ${selected.year}: ${noData ? tr('noData') : fmtFocos(c.focos_armonizados)}`}><span>{m}</span></button>
            })}
          </div>
        </div>}
      </div>

      <div className="nk-spine" aria-label={tr('timeline.years')}>
        <button className="nk-shift" onClick={() => onShiftYear(-1)} disabled={selected.year <= firstYear} aria-label={tr('timeline.prevYear')}><ChevronLeft size={13}/></button>
        <div className="nk-years">
          {years.map((yy) => <button key={yy} className={`${yy === selected.year && !customLabel ? 'is-active' : ''} ${yy === firstYear ? 'is-partial' : ''}`}
            onClick={() => onYear(yy)} title={`${yy}: ${fmtFocos(totals.get(yy) || 0)} ${tr('nk.unit')}`} aria-label={`${yy}: ${fmtFocos(totals.get(yy) || 0)}`}>
            {pixels(totals.get(yy) || 0, maxYear).map((color, k) => <b key={k} style={{ background: color }}/>)}
            <span>{yy % 5 === 0 || yy === selected.year ? `’${String(yy).slice(2)}` : ''}</span>
          </button>)}
        </div>
        <button className="nk-shift" onClick={() => onShiftYear(1)} disabled={selected.year >= lastYear} aria-label={tr('timeline.nextYear')}><ChevronRight size={13}/></button>
      </div>
    </section>
  )
}
