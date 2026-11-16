// Curiosidad: tres clics en el logo → la llama vuela al centro, sus 24 píxeles se ordenan en una fila y esa fila
// es la serpiente de un juego tipo "snake" que come focos de calor. Flechas o WASD (o deslizar en el celular),
// espacio pausa, Esc sale. La serpiente conserva los colores del logo: cola magenta → cabeza amarillo pálido.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { LOGO_VB, PIXELES } from './logoPixeles.js'
import { tr } from './i18n.js'

const COLS = 36, ROWS = 22
const RANGO = { '#b5367a': 0, '#dd513a': 1, '#fca50a': 2, '#fcffa4': 3 }
const RAMPA = ['#b5367a', '#dd513a', '#fca50a', '#fcffa4']
// Cola → cabeza: 6 magenta, 8 brasa, 7 ichu, 3 chispa (las proporciones del logo).
const CORTES = [6 / 24, 14 / 24, 21 / 24]
const colorSegmento = (k, n) => { const f = (k + 0.5) / n; return RAMPA[CORTES.findIndex((c) => f < c) === -1 ? 3 : CORTES.findIndex((c) => f < c)] }
const DIRS = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0], w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0] }

function geometria(origen) {
  const cell = Math.max(10, Math.floor(Math.min((window.innerWidth * 0.92) / COLS, (window.innerHeight * 0.7) / ROWS)))
  const w = COLS * cell, h = ROWS * cell
  const bx = Math.round((window.innerWidth - w) / 2), by = Math.round((window.innerHeight - h) / 2 + 18)
  const s0 = Math.min(origen.width / LOGO_VB.w, origen.height / LOGO_VB.h)
  const oy = origen.top + (origen.height - LOGO_VB.h * s0) / 2
  const s1 = (cell / 25) * 1.9                       // llama grande en el centro
  const cx = window.innerWidth / 2, cy = window.innerHeight / 2
  // Asignación de píxeles a segmentos: cola magenta → cabeza pálida (y de abajo hacia arriba).
  const ordenados = [...PIXELES].sort((a, b) => RANGO[a[2]] - RANGO[b[2]] || b[1] - a[1] || a[0] - b[0])
  const fila = Math.floor(ROWS / 2), x0 = Math.floor((COLS - 24) / 2)
  return {
    cell, w, h, bx, by, fila, x0,
    piezas: ordenados.map(([x, y, c], j) => ({
      c,
      inicio: { left: origen.left + (x - LOGO_VB.x) * s0, top: oy + (y - LOGO_VB.y) * s0, size: 20 * s0 },
      centro: { left: cx + (x - 60) * s1 - 10 * s1, top: cy + (y - 85) * s1 - 10 * s1, size: 20 * s1 },
      fila: { left: bx + (x0 + j) * cell + 1, top: by + fila * cell + 1, size: cell - 2 },
    })),
  }
}

function NikalSnake({ origen, onClose }) {
  const g = useMemo(() => geometria(origen), [origen])
  const [fase, setFase] = useState('inicio')     // inicio → centro → fila → juego
  const [puntos, setPuntos] = useState(0)
  const [estado, setEstado] = useState('listo')   // listo (espera la primera tecla) | jugando | pausa | fin
  const [record, setRecord] = useState(() => Number(window.localStorage?.getItem('nikal.snake') || 0))
  const canvasRef = useRef(null)
  const juego = useRef(null)

  const nuevo = useCallback(() => {
    const cuerpo = Array.from({ length: 24 }, (_, j) => [g.x0 + j, g.fila])   // cola → cabeza
    juego.current = { cuerpo, dir: [1, 0], cola: [], comida: null, crecer: 0, paso: 125 }
    juego.current.comida = libre(cuerpo)
    setPuntos(0); setEstado('listo')
  }, [g])

  // Secuencia de la animación.
  useEffect(() => {
    const t = [setTimeout(() => setFase('centro'), 40), setTimeout(() => setFase('fila'), 1050), setTimeout(() => { nuevo(); setFase('juego') }, 2050)]
    return () => t.forEach(clearTimeout)
  }, [nuevo])

  // La primera dirección arranca el juego; si apunta hacia la cola, la serpiente se da vuelta.
  const estadoRef = useRef(estado)
  estadoRef.current = estado
  const empezar = useCallback((d) => {
    const j = juego.current
    if (!j) return
    if (estadoRef.current === 'listo') {
      if (d[0] === -j.dir[0] && d[1] === -j.dir[1]) j.cuerpo.reverse()
      j.dir = d; j.cola = []
      setEstado('jugando')
    } else j.cola.push(d)
  }, [])

  // Teclado y gestos.
  useEffect(() => {
    const tecla = (e) => {
      if (e.key === 'Escape') { onClose(); return }
      const j = juego.current
      if (!j) return
      if (e.key === ' ') { e.preventDefault(); setEstado((s) => (s === 'jugando' ? 'pausa' : s === 'pausa' ? 'jugando' : s)); return }
      if (e.key === 'Enter') { setEstado((s) => { if (s === 'fin') nuevo(); return s === 'fin' ? 'listo' : s }); return }
      const d = DIRS[e.key] || DIRS[e.key?.toLowerCase?.()]
      if (d) { e.preventDefault(); empezar(d) }
    }
    let toque = null
    const ini = (e) => { toque = [e.touches[0].clientX, e.touches[0].clientY] }
    const fin = (e) => {
      if (!toque || !juego.current) return
      const dx = e.changedTouches[0].clientX - toque[0], dy = e.changedTouches[0].clientY - toque[1]
      if (Math.max(Math.abs(dx), Math.abs(dy)) > 24) empezar(Math.abs(dx) > Math.abs(dy) ? [Math.sign(dx), 0] : [0, Math.sign(dy)])
      toque = null
    }
    window.addEventListener('keydown', tecla)
    window.addEventListener('touchstart', ini, { passive: true })
    window.addEventListener('touchend', fin)
    return () => { window.removeEventListener('keydown', tecla); window.removeEventListener('touchstart', ini); window.removeEventListener('touchend', fin) }
  }, [nuevo, onClose, empezar])

  // Bucle del juego.
  useEffect(() => {
    if (fase !== 'juego' || (estado !== 'jugando' && estado !== 'listo')) return undefined
    let id
    const tick = () => {
      const j = juego.current
      let d = j.dir
      while (j.cola.length) { const n = j.cola.shift(); if (n[0] !== -d[0] || n[1] !== -d[1]) { d = n; break } }
      j.dir = d
      const cab = j.cuerpo[j.cuerpo.length - 1]
      const nx = cab[0] + d[0], ny = cab[1] + d[1]
      const choca = nx < 0 || ny < 0 || nx >= COLS || ny >= ROWS || j.cuerpo.some(([x, y], i) => (i > 0 || j.crecer) && x === nx && y === ny)
      if (choca) {
        setEstado('fin')
        setPuntos((p) => { if (p > record) { setRecord(p); try { window.localStorage?.setItem('nikal.snake', String(p)) } catch { /* privado */ } } return p })
        dibujar(true)
        return
      }
      j.cuerpo.push([nx, ny])
      if (j.comida && nx === j.comida[0] && ny === j.comida[1]) {
        j.crecer += 2; j.comida = libre(j.cuerpo); j.paso = Math.max(65, j.paso - 3); setPuntos((p) => p + 1)
      }
      if (j.crecer > 0) j.crecer -= 1; else j.cuerpo.shift()
      dibujar(false)
      id = setTimeout(tick, j.paso)
    }
    const dibujar = (muerto) => {
      const cv = canvasRef.current
      if (!cv) return
      const ctx = cv.getContext('2d'), c = g.cell, j = juego.current
      ctx.clearRect(0, 0, cv.width, cv.height)
      ctx.fillStyle = 'rgba(245,243,238,.04)'
      for (let x = 0; x < COLS; x++) for (let y = 0; y < ROWS; y++) if ((x + y) % 2) ctx.fillRect(x * c, y * c, c, c)
      if (j.comida) {   // el foco de calor: píxel pálido con halo
        const [fx, fy] = j.comida
        ctx.fillStyle = 'rgba(252,165,10,.25)'; ctx.fillRect(fx * c - 3, fy * c - 3, c + 6, c + 6)
        ctx.fillStyle = '#fcffa4'; redondo(ctx, fx * c + 3, fy * c + 3, c - 6, c - 6, (c - 6) * 0.25)
      }
      j.cuerpo.forEach(([x, y], k) => {
        ctx.fillStyle = muerto ? '#5c5557' : colorSegmento(k, j.cuerpo.length)
        redondo(ctx, x * c + 1, y * c + 1, c - 2, c - 2, (c - 2) * 0.22)
      })
    }
    dibujar(false)
    if (estado === 'jugando') id = setTimeout(tick, juego.current.paso)
    return () => clearTimeout(id)
  }, [fase, estado, g, record])

  const pos = (p) => ({ left: p.left, top: p.top, width: p.size, height: p.size })
  return (
    <div className={`nk-snake is-${fase}`} role="dialog" aria-modal="true" aria-label={tr('snake.aria')}>
      {fase !== 'juego' && g.piezas.map((p, i) => (
        <i key={i} className="nk-snake-px" style={{ ...pos(p[fase] || p.inicio), background: p.c, transitionDelay: fase === 'fila' ? `${i * 18}ms` : `${(23 - i) * 8}ms` }}/>
      ))}
      {fase === 'juego' && <>
        <div className="nk-snake-hud" style={{ left: g.bx, width: g.w, top: g.by - 40 }}>
          <b>{tr('snake.score', { n: puntos })}</b><span>{tr('snake.best', { n: Math.max(record, puntos) })}</span>
          <button onClick={onClose} aria-label={tr('snake.close')} title={tr('snake.close')}><X size={16}/></button>
        </div>
        <canvas ref={canvasRef} width={g.w} height={g.h} className="nk-snake-tablero" style={{ left: g.bx, top: g.by }}/>
        {estado !== 'jugando' && <div className="nk-snake-aviso" style={{ left: g.bx, top: g.by, width: g.w, height: g.h }}>
          <b>{estado === 'fin' ? tr('snake.over', { n: puntos }) : estado === 'listo' ? tr('snake.ready') : tr('snake.paused')}</b>
          <span>{estado === 'fin' ? tr('snake.again') : estado === 'listo' ? tr('snake.readySub') : tr('snake.resume')}</span>
        </div>}
        <p className="nk-snake-ayuda" style={{ top: g.by + g.h + 12 }}>{tr('snake.help')}</p>
      </>}
    </div>
  )
}

function libre(cuerpo) {
  for (;;) {
    const p = [Math.floor(Math.random() * COLS), Math.floor(Math.random() * ROWS)]
    if (!cuerpo.some(([x, y]) => x === p[0] && y === p[1])) return p
  }
}
function redondo(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); ctx.fill()
}

export default NikalSnake
