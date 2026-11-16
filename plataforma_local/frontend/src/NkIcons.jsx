// Íconos propios de Nikal (no genéricos). Mismo trazo en todos (24 × 24, línea 1.6, puntas redondas) y un
// motivo común: la "chispa", un píxel relleno (como los de la llama del logo) que representa el foco de calor:
// el satélite lo detecta como un píxel de 375 m (VIIRS) o 1 km (MODIS).
// Cada ícono cuenta su parte de la historia (montaña andina, órbita, temporada, territorio).
// La chispa usa --nk-spark (brasa por defecto); el resto, currentColor.
const base = (size, children, label) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden={label ? undefined : 'true'} role={label ? 'img' : undefined}
    aria-label={label} className="nk-ico">{children}</svg>
)
const Spark = ({ cx, cy, r = 1.9 }) => <rect x={cx - r} y={cy - r} width={2 * r} height={2 * r} rx={r * 0.4} fill="var(--nk-spark, #dd513a)" stroke="none"/>

// 01 Mirar: ojo cuya pupila es la chispa sobre la línea de una montaña.
export const IcoMirar = ({ size = 18 }) => base(size, <>
  <path d="M2.5 12c2.6-4.2 5.8-6.3 9.5-6.3s6.9 2.1 9.5 6.3c-2.6 4.2-5.8 6.3-9.5 6.3S5.1 16.2 2.5 12Z"/>
  <path d="M7.4 14.6 10 11.6l1.7 1.7 2.2-2.6 2.7 3.9" strokeWidth="1.3"/>
  <Spark cx={12} cy={8.9} r={1.6}/>
</>)

// 02 Entender: globo de diálogo con la curva de la temporada dentro.
export const IcoEntender = ({ size = 18 }) => base(size, <>
  <path d="M4 5.5h16a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5h-8.5L7 21v-3.5H4A1.5 1.5 0 0 1 2.5 16V7A1.5 1.5 0 0 1 4 5.5Z"/>
  <path d="M6 14.2c1.6 0 2.2-4.6 4.4-4.6 2.1 0 2.4 3.1 4 3.1 1.1 0 1.6-1.1 3.6-1.1" strokeWidth="1.4"/>
  <Spark cx={10.4} cy={9.6} r={1.5}/>
</>)

// 03 Comparar: dos montañas separadas por un corte; cada lado con su chispa (antes / después).
export const IcoComparar = ({ size = 18 }) => base(size, <>
  <path d="M12 3v18" strokeDasharray="2 2.2"/>
  <path d="M2.5 18.5 6.5 10l3 5 1.5-2.2"/>
  <path d="M13 18.5l3.2-7.5 2.3 3.6 3-5.6"/>
  <path d="M2.5 18.5h19"/>
  <Spark cx={6.5} cy={7} r={1.3}/>
  <Spark cx={16.2} cy={7.4} r={2}/>
</>)

// 04 Actuar: territorio por niveles (curvas de nivel) con un banderín sobre la chispa.
export const IcoActuar = ({ size = 18 }) => base(size, <>
  <path d="M3.5 17.5c2-3.6 4.6-5.4 8.5-5.4s6.5 1.8 8.5 5.4"/>
  <path d="M6.6 17.5c1.4-2.1 3.1-3 5.4-3s4 .9 5.4 3" strokeWidth="1.3"/>
  <path d="M2.5 20.5h19"/>
  <path d="M12 12.1V3.5l5 2.2-5 2.2"/>
  <Spark cx={12} cy={17.6} r={1.6}/>
</>)

// Focos de calor: llama formada por dos curvas, con la chispa en el centro.
export const IcoFocos = ({ size = 18 }) => base(size, <>
  <path d="M12 21c-3.9 0-6.5-2.6-6.5-6.1 0-3.4 2.6-5.1 3.6-8.4.9 1.4 1.4 2.6 1.6 3.9C12.4 8.3 14 5.6 13.6 3c3.2 2.4 4.9 6.6 4.9 10.6 0 4.4-2.6 7.4-6.5 7.4Z"/>
  <Spark cx={12} cy={16} r={2.1}/>
</>)

// Calendario de la temporada: hoja con anillas y un arco de estación.
export const IcoCalendario = ({ size = 18 }) => base(size, <>
  <rect x="3" y="5" width="18" height="16" rx="2.5"/>
  <path d="M8 3v4M16 3v4M3 10h18"/>
  <path d="M6 18.5c2.4 0 3.2-5.4 6-5.4s3.6 5.4 6 5.4" strokeWidth="1.3"/>
  <Spark cx={12} cy={13.1} r={1.5}/>
</>)

// Área: esquinas de encuadre (como un visor) alrededor de la chispa.
export const IcoArea = ({ size = 18 }) => base(size, <>
  <path d="M3 8V4.5A1.5 1.5 0 0 1 4.5 3H8M16 3h3.5A1.5 1.5 0 0 1 21 4.5V8M21 16v3.5a1.5 1.5 0 0 1-1.5 1.5H16M8 21H4.5A1.5 1.5 0 0 1 3 19.5V16"/>
  <path d="M7 16.5 10.5 11l2 2.7 1.7-2 2.8 4.8" strokeWidth="1.3"/>
  <Spark cx={14.2} cy={8.2} r={1.6}/>
</>)

// Capas: estratos de la montaña apilados.
export const IcoCapas = ({ size = 18 }) => base(size, <>
  <path d="m12 3.5 8.5 4.6L12 12.7 3.5 8.1 12 3.5Z"/>
  <path d="m4.6 12.1 7.4 4 7.4-4" />
  <path d="m4.6 16 7.4 4 7.4-4"/>
  <Spark cx={12} cy={8.1} r={1.5}/>
</>)

// Serie histórica: reloj de arena cuyo grano cae como chispa.
export const IcoHistorico = ({ size = 15 }) => base(size, <>
  <path d="M6 3h12M6 21h12M7.5 3c0 4.5 4.5 5.5 4.5 9s-4.5 4.5-4.5 9M16.5 3c0 4.5-4.5 5.5-4.5 9s4.5 4.5 4.5 9"/>
  <Spark cx={12} cy={17.6} r={1.5}/>
</>)

// En vivo: satélite en órbita sobre la chispa, con ondas.
export const IcoVivo = ({ size = 15 }) => base(size, <>
  <path d="M3 9.5C5.6 5.6 8.6 4 12 4s6.4 1.6 9 5.5" strokeDasharray="1.8 2.2"/>
  <rect x="10" y="2.6" width="4" height="3" rx=".8"/>
  <path d="M7.5 16a6 6 0 0 1 9 0M5 13.5a9.6 9.6 0 0 1 14 0" strokeWidth="1.3"/>
  <Spark cx={12} cy={19} r={2}/>
</>)

// Mapa estándar: plano plegado con un sendero.
export const IcoPlano = ({ size = 14 }) => base(size, <>
  <path d="m3 6 6-2.5 6 2.5 6-2.5v14.5L15 20.5 9 18l-6 2.5V6Z"/>
  <path d="M9 3.5V18M15 6v14.5"/>
</>)

// Relieve: cordillera con nieve.
export const IcoRelieve = ({ size = 14 }) => base(size, <>
  <path d="M2 20 9 7l4 6.5 2.5-3.5L22 20H2Z"/>
  <path d="m7.4 10 1.6 1.4L10.6 10" strokeWidth="1.3"/>
</>)

// Reproducir la temporada: triángulo con la chispa en la punta.
export const IcoPlay = ({ size = 16 }) => base(size, <>
  <path d="M7 4.5v15l11.5-7.5L7 4.5Z" fill="currentColor"/>
</>)
export const IcoPausa = ({ size = 16 }) => base(size, <>
  <rect x="6" y="4.5" width="4" height="15" rx="1.2" fill="currentColor"/>
  <rect x="14" y="4.5" width="4" height="15" rx="1.2" fill="currentColor"/>
</>)

// Ajustes de capas: tres reglas cuyos cursores son chispas.
export const IcoAjustes = ({ size = 18 }) => base(size, <>
  <path d="M3.5 6.5h17M3.5 12h17M3.5 17.5h17" strokeWidth="1.4"/>
  <Spark cx={8} cy={6.5} r={2}/>
  <Spark cx={15.5} cy={12} r={2}/>
  <Spark cx={10.5} cy={17.5} r={2}/>
</>)

// Lo habitual: línea punteada de la mediana con la chispa encima (lo de este periodo).
export const IcoHabitual = ({ size = 16 }) => base(size, <>
  <path d="M3 15.5h18" strokeDasharray="2.2 2.4"/>
  <path d="M3 19c3.5 0 4.5-9 9-9s5.5 9 9 9" strokeWidth="1.4"/>
  <Spark cx={12} cy={10} r={1.9}/>
</>)

// Satélite (MODIS / VIIRS): cuerpo con dos paneles y su mirada hacia la chispa.
export const IcoSatelite = ({ size = 16 }) => base(size, <>
  <rect x="9.5" y="4.5" width="5" height="6" rx="1"/>
  <path d="M9.5 7.5H3.5M14.5 7.5h6M4 5v5M20 5v5"/>
  <path d="m10 14.5-2 3.5M14 14.5l2 3.5" strokeWidth="1.3" strokeDasharray="1.4 1.6"/>
  <Spark cx={12} cy={19.5} r={1.9}/>
</>)

// ---------- Íconos de píxeles (menú derecho) ----------
// Mismo lenguaje que la llama del logo: se dibujan sobre una grilla de 12 × 12 con píxeles de esquinas suaves.
// '#' = color del texto, '*' = chispa (foco de calor), '.' = vacío. Referencia de estilo: pixelarticons (MIT);
// los dibujos son propios.
function Pixeles({ size, filas, label }) {
  const rects = []
  filas.forEach((fila, y) => [...fila].forEach((c, x) => {
    if (c === '.') return
    rects.push(<rect key={`${x}-${y}`} x={x * 2 + 0.15} y={y * 2 + 0.15} width="1.7" height="1.7" rx="0.45"
      fill={c === '*' ? 'var(--nk-spark, #dd513a)' : 'currentColor'}/>)
  }))
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden={label ? undefined : 'true'} role={label ? 'img' : undefined} aria-label={label} className="nk-ico nk-ico-px">{rects}</svg>
}
const px = (filas) => function IcoPx({ size = 20, label }) { return <Pixeles size={size} filas={filas} label={label}/> }

// Herramientas: cuatro bloques, uno encendido (abre el estuche).
export const IcoPxHerramientas = px([
  '............', '.###....***.', '.###....***.', '.###....***.', '............', '............',
  '............', '.###....###.', '.###....###.', '.###....###.', '............', '............'])
// Capas: estratos del terreno apilados, con la chispa en la cima.
export const IcoPxCapas = px([
  '............', '.....**.....', '....####....', '...######...', '............', '..########..',
  '............', '.##########.', '............', '############', '............', '............'])
// Área: esquinas de selección alrededor de un grupo de píxeles encendidos.
export const IcoPxArea = px([
  '###......###', '#..........#', '#..........#', '............', '....**......', '....***.....',
  '.....**.....', '............', '#..........#', '#..........#', '###......###', '............'])
// Comparar: dos llamas de distinto tamaño (antes y después).
export const IcoPxComparar = px([
  '.........*..', '........##..', '..*.....###.', '..##...####.', '.###...####.', '.###..#####.',
  '.###..#####.', '.###..#####.', '..#....###..', '............', '#####.######', '............'])
// Calendario: grilla de días con uno encendido.
export const IcoPxCalendario = px([
  '..#......#..', '############', '............', '##.##.##.##.', '##.##.##.##.', '............',
  '##.##.**.##.', '##.##.**.##.', '............', '##.##.##....', '##.##.##....', '............'])
// Peligro CENEPRED: cuatro niveles escalonados, el más alto encendido.
export const IcoPxPeligro = px([
  '............', '.........**.', '.........**.', '......##.**.', '......##.**.', '...##.##.**.',
  '...##.##.**.', '##.##.##.**.', '##.##.##.**.', '##.##.##.**.', '............', '############'])
