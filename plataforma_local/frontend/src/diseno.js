// Diseño "Nikal" (vista local). ?diseno=dante vuelve al diseño de Dante para comparar.
//
// Paleta narrativa tomada del logo (nikal-icono.svg, escala "inferno"); cada color tiene un papel fijo:
//   Noche    #121011  el escenario: superficies oscuras sobre el mapa.
//   Papel    #f5f3ee  la libreta de campo (el texto del logo).  Tinta #141210: texto y contornos.
//   Magenta  #b5367a  el borde de la llama: sombras duras y el inicio del recorrido.
//   Brasa    #dd513a / #b83a24  el fuego: lo que pasó y la acción principal.
//   Ichu     #fca50a  el territorio y el tiempo: Cusco, el área dibujada, lo elegido.
//   Chispa   #fcffa4  la punta de la llama: la cifra y el elemento activo.
//   Habitual #bdb7ad  lo habitual (medianas): gris claro punteado en toda la app; el año siempre en ichu.
//   Puna     #7fb7b2 / #3f6f74  referencia fría en los gráficos del diseño anterior (frío, para contrastar con la brasa
//            también con daltonismo).
// Los colores de datos (escala de calor, anomalía, niveles CENEPRED, sensores, En vivo) no cambian.
export const NK = typeof window === 'undefined' || new URLSearchParams(window.location.search).get('diseno') !== 'dante'

export const PALETA = {
  noche: '#121011', papel: '#f5f3ee', tinta: '#141210', magenta: '#b5367a',
  brasa: '#dd513a', brasaHonda: '#b83a24', ichu: '#fca50a', chispa: '#fcffa4',
  puna: '#7fb7b2', punaHonda: '#3f6f74',
}

// Colores de las capas del mapa (MapLibre no lee CSS).
export const MAPA = NK
  ? { mascara: '#0b0a0a', area: PALETA.ichu, areaRelleno: PALETA.ichu, seleccion: PALETA.chispa, regionA: PALETA.ichu, regionB: PALETA.ichu }
  : { mascara: '#0b1712', area: '#0f766e', areaRelleno: '#0f766e', seleccion: '#5ee7d7', regionA: '#178bb9', regionB: '#39bce8' }
