// Cliente de la API de Nikal (backend FastAPI de plataforma_local).
// Por defecto usa la misma dirección que sirve la página. Para un frontend publicado aparte
// (p. ej. Vercel), define VITE_API_BASE_URL con la URL del backend.
import { getLang, tr } from '../i18n.js'

const configuredApiUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
// En Vercel usamos /api en el mismo dominio y vercel.json reenvía la petición a Cloud Run.
// Esto evita depender de CORS y mantiene VITE_API_BASE_URL disponible para otros hosts.
const API_BASE_URL = window.location.hostname.endsWith('.vercel.app') ? '' : configuredApiUrl

export const CUSCO = 'PE-CUS'

function buildUrl(path, params = {}) {
  const url = new URL(`${API_BASE_URL}${path}`, window.location.href)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') url.searchParams.set(key, value)
  })
  url.searchParams.set('lang', getLang())          // textos de la API en el idioma de la interfaz
  return url
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function request(path, params, retry = true) {
  const response = await fetch(buildUrl(path, params))
  // 429 (cupo por IP) o 503 (servidor ocupado): esperar lo que pide Retry-After y reintentar una vez.
  if (retry && (response.status === 429 || response.status === 503)) {
    const wait = Math.min(6, Number(response.headers.get('Retry-After')) || 2)
    await sleep(wait * 1000)
    return request(path, params, false)
  }
  let body = null
  try { body = await response.json() } catch { /* respuesta sin JSON */ }
  if (!response.ok) {
    const detail = body?.detail
    const error = new Error(typeof detail === 'string' ? detail : tr('api.status', { s: response.status }))
    error.status = response.status
    error.retryAfter = response.headers.get('Retry-After')
    throw error
  }
  return { body, ms: response.headers.get('X-Process-Time-ms') }
}

// AOI: { departamento: 'PE-CUS' } o { bbox: 'oeste,sur,este,norte' }
export const getRegion = () => request('/api/departamentos.geojson')
export const getDepartments = () => request('/api/departamentos')
export const getMetadata = () => request('/api/metadatos')
export const getCalendar = (aoi, fechaInicio, fechaFin) =>
  request('/api/calendario', { ...aoi, fecha_inicio: fechaInicio, fecha_fin: fechaFin })
export const getMonth = (aoi, mes) => request('/api/anomalias', { ...aoi, mes })
// Analíticas "en simple": cada respuesta trae titulo, en_simple, como_leerlo y los datos.
export const getResumen = (aoi, extra = {}) => request('/api/resumen', { ...aoi, ...extra })
export const getAnalitica = (nombre, aoi, extra = {}) => request(`/api/analitica/${nombre}`, { ...aoi, ...extra })
// Detecciones casi en tiempo real (NASA FIRMS, sin armonizar). Sin reintento: si el servidor no
// tiene MAP_KEY responde 503 y se muestra el mensaje enseguida.
export const getTiempoReal = (horas) => request('/api/tiempo-real', { horas }, false)
// Ámbitos: nivel de peligro por focos de calor (formato CENEPRED) e informes.
export const getAmbitos = () => request('/api/ambitos')
export const getAmbitoNivel = (nivel) => request(`/api/ambitos/${nivel}`)
// Focos por día del año según el nivel de peligro (se calcula al pedirlo: años y ventana de suavizado).
export const getAmbitoDias = (nivel, params) => request(`/api/ambitos/${nivel}/dias`, params)
export const getAmbitoDia = (nivel, dia, params) => request(`/api/ambitos/${nivel}/dias/${dia}`, params)
export const getAmbitoGeojson = (nivel) => request(`/api/ambitos/${nivel}.geojson`)
export const ambitoUrl = (path) => buildUrl(path).toString()
// Informe técnico imprimible (HTML) de cualquier área y periodo; opcional mes=AAAA-MM.
export const informeUrl = (aoi, extra = {}) => buildUrl('/api/informe', { ...aoi, ...extra }).toString()
export const getFocos = (aoi, fechaInicio, fechaFin) =>
  request('/api/focos.geojson', { ...aoi, fecha_inicio: fechaInicio, fecha_fin: fechaFin })

// Descarga del CSV de focos (18 columnas del contrato). Se usa fetch para mostrar los errores.
export async function downloadCsv(aoi, fechaInicio, fechaFin) {
  const response = await fetch(buildUrl('/api/hotspots.csv', { ...aoi, fecha_inicio: fechaInicio, fecha_fin: fechaFin }))
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || tr('api.status', { s: response.status }))
  }
  const blob = await response.blob()
  const name = (response.headers.get('Content-Disposition') || '').match(/filename="(.+)"/)?.[1] || 'focos_cusco.csv'
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = name
  link.click()
  URL.revokeObjectURL(link.href)
  return { rows: Number(response.headers.get('X-Row-Count')), total: Number(response.headers.get('X-Total-Eq-Foco')) }
}
