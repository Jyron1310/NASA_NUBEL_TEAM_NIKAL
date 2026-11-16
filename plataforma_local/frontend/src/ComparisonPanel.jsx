import { useMemo } from 'react'
import { ChartNoAxesCombined, Download, MapPin, ShieldCheck, X } from 'lucide-react'
import { locale, months, tr } from './i18n.js'

const value = (cell, key) => Number(cell?.[key]) || 0
const format = (number, digits = 0) => Number(number || 0).toLocaleString(locale(), { maximumFractionDigits: digits })

function summarize(cells, period) {
  const fromMonth = period.from.slice(0, 7)
  const toMonth = period.to.slice(0, 7)
  const selected = cells.filter((cell) => {
    const key = `${cell.anio}-${String(cell.mes).padStart(2, '0')}`
    return key >= fromMonth && key <= toMonth
  })
  const series = Array.from({ length: 12 }, (_, index) => selected.filter((cell) => cell.mes === index + 1).reduce((sum, cell) => sum + value(cell, 'focos_armonizados'), 0))
  const total = series.reduce((sum, current) => sum + current, 0)
  const peakIndex = series.indexOf(Math.max(...series))
  return {
    label: `${period.from} – ${period.to}`,
    series,
    total,
    cellDays: selected.reduce((sum, cell) => sum + value(cell, 'celdas_dia'), 0),
    activeMonths: selected.filter((cell) => value(cell, 'focos_armonizados') > 0).length,
    peakIndex,
    peak: series[peakIndex] || 0,
    quality: [...new Set(selected.map((cell) => cell?.calidad).filter(Boolean))],
  }
}

function MonthlyBars({ first, second }) {
  const labels = months().map((month) => month.slice(0, 3))
  const width = 860; const height = 260; const left = 48; const top = 26; const bottom = 42
  const chartHeight = height - top - bottom; const chartWidth = width - left - 18
  const maximum = Math.max(1, ...first.series, ...second.series)
  const group = chartWidth / 12; const bar = Math.max(7, group * 0.27)
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  return <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={tr('compare.monthlyChart')}>
    {ticks.map((tick) => { const y = top + chartHeight * (1 - tick); return <g key={tick}><line x1={left} x2={width - 18} y1={y} y2={y} className="fc-compare-grid"/><text x={left - 8} y={y + 3} textAnchor="end">{format(maximum * tick)}</text></g> })}
    {labels.map((label, index) => {
      const x = left + group * index + group / 2
      const firstHeight = chartHeight * first.series[index] / maximum
      const secondHeight = chartHeight * second.series[index] / maximum
      return <g key={label}>
        <rect className="is-first" x={x - bar - 2} y={top + chartHeight - firstHeight} width={bar} height={firstHeight} rx="2"/>
        <rect className="is-second" x={x + 2} y={top + chartHeight - secondHeight} width={bar} height={secondHeight} rx="2"/>
        <text x={x} y={height - 17} textAnchor="middle">{label}</text>
      </g>
    })}
  </svg>
}

function CumulativeLines({ first, second }) {
  const width = 860; const height = 230; const left = 48; const top = 25; const bottom = 36
  const chartHeight = height - top - bottom; const chartWidth = width - left - 18
  const cumulative = (series) => series.reduce((all, current) => [...all, current + (all.at(-1) || 0)], [])
  const a = cumulative(first.series); const b = cumulative(second.series)
  const maximum = Math.max(1, ...a, ...b)
  const points = (series) => series.map((current, index) => `${left + chartWidth * index / 11},${top + chartHeight * (1 - current / maximum)}`).join(' ')
  return <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={tr('compare.cumulativeChart')}>
    {[0, 0.5, 1].map((tick) => { const y = top + chartHeight * (1 - tick); return <g key={tick}><line x1={left} x2={width - 18} y1={y} y2={y} className="fc-compare-grid"/><text x={left - 8} y={y + 3} textAnchor="end">{format(maximum * tick)}</text></g> })}
    <polyline className="is-first" points={points(a)}/><polyline className="is-second" points={points(b)}/>
    {a.map((current, index) => <circle key={`a-${index}`} className="is-first" cx={left + chartWidth * index / 11} cy={top + chartHeight * (1 - current / maximum)} r="3"/>)}
    {b.map((current, index) => <circle key={`b-${index}`} className="is-second" cx={left + chartWidth * index / 11} cy={top + chartHeight * (1 - current / maximum)} r="3"/>)}
    <text x={left} y={height - 13}>Jan</text><text x={width - 18} y={height - 13} textAnchor="end">Dec</text>
  </svg>
}

function downloadComparison(first, second) {
  const labels = months()
  const rows = [['month', first.label, second.label, 'difference'], ...labels.map((label, index) => [label, first.series[index], second.series[index], second.series[index] - first.series[index]])]
  const blob = new Blob([rows.map((row) => row.join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob); link.download = `nubel_comparison_${first.label.slice(0, 7)}_${second.label.slice(0, 7)}.csv`; link.click()
  URL.revokeObjectURL(link.href)
}

export default function ComparisonPanel({ calendar, calendarA, calendarB, regionName, periodA, periodB, onClose }) {
  const cellsA = useMemo(() => calendarA?.celdas || calendar?.celdas || [], [calendar, calendarA])
  const cellsB = useMemo(() => calendarB?.celdas || calendar?.celdas || [], [calendar, calendarB])
  const first = useMemo(() => summarize(cellsA, periodA), [cellsA, periodA])
  const second = useMemo(() => summarize(cellsB, periodB), [cellsB, periodB])
  const difference = second.total - first.total
  const percent = first.total ? difference / first.total * 100 : null
  const changes = second.series.map((current, index) => ({ index, value: current - first.series[index] }))
  const largest = changes.reduce((winner, current) => Math.abs(current.value) > Math.abs(winner.value) ? current : winner, changes[0] || { index: 0, value: 0 })
  const changeText = percent === null ? tr('compare.notComparable') : Math.abs(percent) < 1
    ? tr('compare.stable')
    : tr(percent > 0 ? 'compare.increased' : 'compare.decreased', { pct: format(Math.abs(percent), 1) })
  const conclusion = tr('compare.conclusion', { a: first.label, b: second.label, change: changeText, month: months()[largest.index], delta: `${largest.value >= 0 ? '+' : '−'}${format(Math.abs(largest.value), 1)}` })

  if (!cellsA.length && !cellsB.length) return <aside className="fc-compare-panel"><div className="fc-compare-empty">{tr('summary.loading')}</div></aside>
  return <aside className="fc-compare-panel" aria-label={tr('compare.title')}>
    <header className="fc-compare-head">
      <div><p>{tr('compare.kicker')}</p><h2>{tr('compare.title')}</h2><span><MapPin size={12}/>{regionName} · {tr('compare.validated')}</span></div>
      <div className="fc-compare-selectors"><label><span>{tr('compare.periodA')}</span><b>{first.label}</b></label><label><span>{tr('compare.periodB')}</span><b>{second.label}</b></label></div>
      <button className="fc-compare-close" onClick={onClose} title={tr('btn.close')}><X size={18}/></button>
    </header>
    <div className="fc-compare-body">
      <section className="fc-compare-summary">
        <div><span>{tr('compare.executive')}</span><p>{conclusion}</p></div>
        <ShieldCheck size={22}/>
      </section>
      <section className="fc-compare-metrics">
        <article><span>{tr('metric.hotspots')}</span><div><b>{format(first.total, 1)}</b><i>A</i></div><div><b>{format(second.total, 1)}</b><i>B</i></div><strong className={difference >= 0 ? 'is-up' : 'is-down'}>{difference >= 0 ? '+' : '−'}{format(Math.abs(difference), 1)}</strong></article>
        <article><span>{tr('metric.cellDays')}</span><div><b>{format(first.cellDays)}</b><i>A</i></div><div><b>{format(second.cellDays)}</b><i>B</i></div><strong>{second.cellDays - first.cellDays >= 0 ? '+' : '−'}{format(Math.abs(second.cellDays - first.cellDays))}</strong></article>
        <article><span>{tr('compare.peakMonth')}</span><div><b>{months()[first.peakIndex]}</b><i>{format(first.peak, 1)}</i></div><div><b>{months()[second.peakIndex]}</b><i>{format(second.peak, 1)}</i></div><strong>{tr('compare.monthlyPeak')}</strong></article>
        <article><span>{tr('metric.monthsFire')}</span><div><b>{first.activeMonths}</b><i>A</i></div><div><b>{second.activeMonths}</b><i>B</i></div><strong>{tr('compare.ofPeriod')}</strong></article>
      </section>
      <div className="fc-compare-grid-layout">
        <section className="fc-compare-chart"><header><div><span>01</span><h3>{tr('compare.monthly')}</h3></div><p>{tr('compare.monthlyHelp')}</p></header><div className="fc-compare-legend"><i className="is-first"/>A<i className="is-second"/>B</div><MonthlyBars first={first} second={second}/></section>
        <section className="fc-compare-chart"><header><div><span>02</span><h3>{tr('compare.cumulative')}</h3></div><p>{tr('compare.cumulativeHelp')}</p></header><div className="fc-compare-legend"><i className="is-first"/>A<i className="is-second"/>B</div><CumulativeLines first={first} second={second}/></section>
      </div>
      <section className="fc-compare-notes"><ChartNoAxesCombined size={18}/><div><b>{tr('compare.interpretation')}</b><small>{tr('compare.quality')}: {first.quality.join(', ') || '—'} / {second.quality.join(', ') || '—'}</small></div></section>
    </div>
    <footer className="fc-compare-footer"><span>NASA FIRMS · Nubel Team · UTC−5</span><button onClick={() => downloadComparison(first, second)}><Download size={14}/>{tr('compare.csv')}</button></footer>
  </aside>
}
