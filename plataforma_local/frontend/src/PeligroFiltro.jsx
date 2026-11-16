// Filtro "Peligro CENEPRED" dentro de Capas: muestra cómo se reparten los focos del periodo de la barra inferior
// según el nivel de peligro (formato CENEPRED) de la provincia o distrito donde caen, y permite ver en el mapa
// solo los focos de uno o varios niveles. Cálculo en peligro.js; unidades de /api/ambitos/{nivel}.geojson.
import { IcoPxPeligro } from './NkIcons.jsx'
import { NIVELES } from './peligro.js'
import { locale, tr } from './i18n.js'

const COLOR = { muy_alto: '#c0392b', alto: '#e67e22', medio: '#f1c40f', bajo: '#27ae60' }
const pct = (v) => {
  const p = 100 * v
  return (p > 0 && p < 1 ? p.toFixed(1) : Math.round(p)).toLocaleString(locale())
}

function PeligroFiltro({ peligro, setPeligro, clase }) {
  const alternarNivel = (n) => setPeligro((p) => ({ ...p, solo: p.solo.includes(n) ? p.solo.filter((x) => x !== n) : [...p.solo, n] }))
  return (
    <section className={`nk-peligro ${peligro.on ? 'is-on' : ''}`}>
      <button className="nk-peligro-tog" aria-pressed={peligro.on} onClick={() => setPeligro((p) => ({ ...p, on: !p.on, solo: [] }))}>
        <IcoPxPeligro size={22}/>
        <span><b>{tr('nk.peligro.title')}</b></span>
        <i className="nk-switch" aria-hidden="true"/>
      </button>
      {peligro.on && <>
        <div className="nk-peligro-ambito" role="group" aria-label={tr('amb.scope')}>
          {['provincia', 'distrito'].map((n) => <button key={n} aria-pressed={peligro.nivel === n} className={peligro.nivel === n ? 'is-active' : ''}
            onClick={() => setPeligro((p) => ({ ...p, nivel: n, solo: [] }))}>{tr(`nk.peligro.${n}`)}</button>)}
        </div>
        {!clase ? <p className="nk-peligro-nota">{tr('nk.peligro.loading')}</p> : <>
          <ul className="nk-peligro-niveles">
            {NIVELES.map((n) => {
              const activo = peligro.solo.includes(n)
              return <li key={n}>
                <button aria-pressed={activo} className={`${activo ? 'is-active' : ''} ${peligro.solo.length && !activo ? 'is-apagado' : ''}`} onClick={() => alternarNivel(n)}>
                  <i style={{ background: COLOR[n] }}/><span>{tr(`amb.level.${n}`)}</span><b>{pct(clase.parte[n] || 0)} %</b>
                  <em><s style={{ width: `${Math.min(100, 100 * (clase.parte[n] || 0))}%`, background: COLOR[n] }}/></em>
                </button>
              </li>
            })}
          </ul>
          {clase.parte.sin_unidad > 0.001 && <p className="nk-peligro-nota">{tr('nk.peligro.outside', { p: pct(clase.parte.sin_unidad) })}</p>}
        </>}
      </>}
    </section>
  )
}

export default PeligroFiltro
