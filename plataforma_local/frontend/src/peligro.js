// Distribución de los focos según el nivel de peligro CENEPRED de la unidad donde caen (filtro de la capa
// "Peligro CENEPRED"). Las unidades vienen de /api/ambitos/{nivel}.geojson; cada foco se asigna a la unidad
// que lo contiene (punto en polígono, con descarte previo por recuadro). Los focos fuera de toda unidad
// (borde de Cusco, ~1,7 %) quedan como "sin_unidad".
export const NIVELES = ['muy_alto', 'alto', 'medio', 'bajo']

function anillos(geom) {
  return geom.type === 'MultiPolygon' ? geom.coordinates : geom.type === 'Polygon' ? [geom.coordinates] : []
}
function dentroAnillo(x, y, a) {
  let dentro = false
  for (let i = 0, j = a.length - 1; i < a.length; j = i++) {
    const [xi, yi] = a[i], [xj, yj] = a[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dentro = !dentro
  }
  return dentro
}
function dentroPoligono(x, y, poligonos) {
  return poligonos.some((p) => dentroAnillo(x, y, p[0]) && !p.slice(1).some((h) => dentroAnillo(x, y, h)))
}

export function prepararUnidades(geojson) {
  return (geojson?.features || []).map((f) => {
    const pols = anillos(f.geometry)
    let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity
    pols.forEach((p) => p[0].forEach(([x, y]) => { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y) }))
    return { pols, caja: [w, s, e, n], nivel: f.properties.nivel_peligro, codigo: f.properties.codigo, area: Number(f.properties.area_km2) || 0 }
  })
}

// Nivel de peligro de cada foco (mismo orden que las features) y parte de los focos armonizados por nivel.
export function clasificar(focos, unidades) {
  const suma = { muy_alto: 0, alto: 0, medio: 0, bajo: 0, sin_clasificar: 0, sin_unidad: 0 }
  const porUnidad = new Map()     // focos armonizados del periodo en cada unidad (para pintar el mapa)
  let total = 0
  const niveles = (focos?.features || []).map((f) => {
    const [x, y] = f.geometry.coordinates
    const u = unidades.find(({ caja: [w, s, e, n], pols }) => x >= w && x <= e && y >= s && y <= n && dentroPoligono(x, y, pols))
    const nivel = u ? u.nivel : 'sin_unidad'
    const peso = Number(f.properties?.eq_foco) || 0
    suma[nivel] = (suma[nivel] || 0) + peso
    if (u) porUnidad.set(u.codigo, (porUnidad.get(u.codigo) || 0) + peso)
    total += peso
    return nivel
  })
  const parte = Object.fromEntries(Object.entries(suma).map(([k, v]) => [k, total > 0 ? v / total : 0]))
  // Actividad 0-1 de cada unidad en el periodo: densidad (focos por km²) frente a la unidad más activa,
  // con raíz cuadrada para que las unidades con pocos focos también se distingan.
  const dens = unidades.map((u) => [u.codigo, u.area > 0 ? (porUnidad.get(u.codigo) || 0) / u.area : 0])
  const max = Math.max(0, ...dens.map(([, d]) => d))
  const actividad = new Map(dens.map(([c, d]) => [c, max > 0 ? Math.sqrt(d / max) : 0]))
  return { niveles, parte, total, actividad }
}
