/* Gráficos sencillos de las analíticas (/api/analitica/*), en SVG y sin dependencias.
 * Cada función recibe la respuesta de la API y devuelve { svg, csv }: el dibujo y sus datos.
 * Origen: antonio/backend-modelo (plataforma_local/frontend/charts.js), como módulo ES.
 * Colores aptos para daltonismo: azul (habitual), naranja (destacado), gris (rango o referencia). */
const W = 560, H = 250, M = { l: 46, r: 14, t: 14, b: 34 };
// Con el diseño Nikal: lo habitual en puna (frío), lo destacado en brasa, papel y tinta cálidos.
const AZUL = NK ? "#3f6f74" : "#31688e", AZUL_CLARO = NK ? "#a9cfcb" : "#9ecae1", NARANJA = NK ? "#dd513a" : "#c2410c",
  GRIS = NK ? "#9c968c" : "#98a2b3", TINTA = NK ? "#141210" : "#1d2330", BANDA = NK ? "#e1ddd3" : "#dbe4ee";
const FONDO = NK ? "#f5f3ee" : "#fff", REJILLA = NK ? "#dcd7cc" : "#e4e7ec", EJE = NK ? "#6b655d" : "#5d6677";
const FUENTE = NK ? "'Nikal Grotesk', system-ui, sans-serif" : "system-ui, sans-serif";
import { locale, monthLetters, tr } from "./i18n.js";
import { NK } from "./diseno.js";

const fmt = (v) => Math.round(v).toLocaleString(locale());
const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

// Tope "redondo" del eje: 1, 2, 2.5 o 5 por una potencia de diez.
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  return [1, 2, 2.5, 5, 10].map((k) => k * p).find((k) => k >= v);
}
function frame(body, desc) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(desc)}" font-family="${FUENTE}" font-size="11"><rect width="${W}" height="${H}" fill="${FONDO}"/>${body}</svg>`;
}
function yAxis(max, unidad) {
  const y = (v) => M.t + (H - M.t - M.b) * (1 - v / max);
  const ticks = [0, max / 2, max].map((v) => `<line x1="${M.l}" x2="${W - M.r}" y1="${y(v)}" y2="${y(v)}" stroke="${REJILLA}"/><text x="${M.l - 6}" y="${y(v) + 4}" text-anchor="end" fill="${TINTA}">${fmt(v)}</text>`).join("");
  return { y, svg: ticks + `<text x="12" y="${M.t + (H - M.t - M.b) / 2}" transform="rotate(-90 12 ${M.t + (H - M.t - M.b) / 2})" text-anchor="middle" fill="${EJE}">${esc(unidad)}</text>` };
}
const csv = (rows) => rows.map((r) => r.join(",")).join("\n");

// 1. Barras por mes: altura = lo habitual (mediana); línea vertical = entre qué valores cae la mitad de los años.
function estacionalidad(d) {
  const max = niceMax(Math.max(...d.meses.map((m) => m.p75)));
  const MES = monthLetters(), ax = yAxis(max, tr("chart.unit")), bw = (W - M.l - M.r) / 12;
  const bars = d.meses.map((m, i) => {
    const x = M.l + i * bw, cx = x + bw / 2, color = m.mes === d.mes_pico ? NARANJA : m.en_temporada ? AZUL : AZUL_CLARO;
    return `<rect x="${x + 4}" y="${ax.y(m.mediana)}" width="${bw - 8}" height="${ax.y(0) - ax.y(m.mediana)}" fill="${color}"><title>${esc(tr("chart.monthTip", { m: m.nombre, v: fmt(m.mediana), a: fmt(m.p25), b: fmt(m.p75) }))}</title></rect>` +
      `<line x1="${cx}" x2="${cx}" y1="${ax.y(m.p25)}" y2="${ax.y(m.p75)}" stroke="${TINTA}" stroke-width="1.5"/>` +
      `<text x="${cx}" y="${H - M.b + 14}" text-anchor="middle" fill="${TINTA}">${MES[i]}</text>`;
  }).join("");
  // Posiciones según el largo de cada texto (cambia con el idioma): ~6 px por carácter a 11 px.
  const [l1, l2, l3] = [tr("chart.peak"), tr("chart.season"), tr("chart.rest")];
  const x2 = 14 + l1.length * 6 + 14, x3 = x2 + 14 + l2.length * 6 + 14;
  const leyenda = `<g transform="translate(${M.l + 6} ${M.t + 2})"><rect width="10" height="10" fill="${NARANJA}"/><text x="14" y="9">${esc(l1)}</text><rect x="${x2}" width="10" height="10" fill="${AZUL}"/><text x="${x2 + 14}" y="9">${esc(l2)}</text><rect x="${x3}" width="10" height="10" fill="${AZUL_CLARO}"/><text x="${x3 + 14}" y="9">${esc(l3)}</text></g>`;
  return { svg: frame(ax.svg + bars + leyenda, d.en_simple),
           csv: csv([["mes", "nombre", "mediana", "p25", "p75", "parte_del_anio", "en_temporada"], ...d.meses.map((m) => [m.mes, m.nombre, m.mediana, m.p25, m.p75, m.parte_del_anio, m.en_temporada])]) };
}

// 2. Una barra por año, en orden de tiempo; la línea punteada es un año típico.
function ranking(d) {
  const anios = [...d.anios].sort((a, b) => a.anio - b.anio), top = d.anios.find((a) => a.calidad === "ok");
  const max = niceMax(Math.max(...anios.map((a) => a.total))), ax = yAxis(max, tr("chart.unit")), bw = (W - M.l - M.r) / anios.length;
  const bars = anios.map((a, i) => {
    const x = M.l + i * bw, ext = a.calidad !== "ok", color = a.anio === top.anio ? NARANJA : AZUL;
    return `<rect x="${x + 2}" y="${ax.y(a.total)}" width="${bw - 4}" height="${ax.y(0) - ax.y(a.total)}" fill="${color}" opacity="${ext ? 0.4 : 1}"><title>${tr("chart.yearTip", { y: a.anio, v: fmt(a.total), p: a.puesto })}${ext ? tr("chart.extrapTip", { v: fmt(a.incertidumbre) }) : ""}</title></rect>` +
      (a.anio % 5 === 0 ? `<text x="${x + bw / 2}" y="${H - M.b + 14}" text-anchor="middle" fill="${TINTA}">${a.anio}</text>` : "");
  }).join("");
  const yt = ax.y(d.anio_tipico);
  const tipico = `<line x1="${M.l}" x2="${W - M.r}" y1="${yt}" y2="${yt}" stroke="${TINTA}" stroke-dasharray="4 3"/><text x="${W - M.r - 2}" y="${yt - 4}" text-anchor="end" fill="${TINTA}">${tr("chart.typical", { v: fmt(d.anio_tipico) })}</text>`;
  return { svg: frame(ax.svg + bars + tipico, d.en_simple),
           csv: csv([["anio", "total", "puesto", "respecto_al_tipico", "calidad", "incertidumbre"], ...anios.map((a) => [a.anio, a.total, a.puesto, a.respecto_al_tipico, a.calidad, a.incertidumbre])]) };
}

// 3. Curva acumulada del año sobre la banda donde cae la mayoría de los años.
function acumulado(d) {
  const c = d.curva, max = niceMax(Math.max(...c.map((p) => Math.max(p.alto, p.acumulado))));
  const MES = monthLetters(), ax = yAxis(max, tr("chart.unitSum")), x = (dia) => M.l + (W - M.l - M.r) * (dia - 1) / 364;
  const linea = (k) => c.map((p, i) => `${i ? "L" : "M"}${x(p.dia).toFixed(1)} ${ax.y(p[k]).toFixed(1)}`).join(" ");
  const banda = `M${c.map((p) => `${x(p.dia).toFixed(1)} ${ax.y(p.alto).toFixed(1)}`).join(" L")} L${[...c].reverse().map((p) => `${x(p.dia).toFixed(1)} ${ax.y(p.bajo).toFixed(1)}`).join(" L")} Z`;
  const inicio = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];
  const meses = inicio.map((dia, i) => `<line x1="${x(dia)}" x2="${x(dia)}" y1="${H - M.b}" y2="${H - M.b + 4}" stroke="${GRIS}"/><text x="${x(dia + 15)}" y="${H - M.b + 15}" text-anchor="middle" fill="${TINTA}">${MES[i]}</text>`).join("");
  const leyenda = `<g transform="translate(${M.l + 6} ${M.t + 2})"><line x2="16" y1="5" y2="5" stroke="${NARANJA}" stroke-width="3"/><text x="20" y="9">${d.anio}</text><line x1="62" x2="78" y1="5" y2="5" stroke="${TINTA}" stroke-dasharray="4 3"/><text x="82" y="9">${esc(tr("chart.usual"))}</text><rect x="${82 + tr("chart.usual").length * 6 + 14}" width="14" height="10" fill="${BANDA}"/><text x="${82 + tr("chart.usual").length * 6 + 32}" y="9">${esc(tr("chart.band"))}</text></g>`;
  return { svg: frame(ax.svg + `<path d="${banda}" fill="${BANDA}"/><path d="${linea("normal")}" fill="none" stroke="${TINTA}" stroke-dasharray="4 3"/><path d="${linea("acumulado")}" fill="none" stroke="${NARANJA}" stroke-width="3"/>` + meses + leyenda, d.en_simple),
           csv: csv([["dia_del_anio", `acumulado_${d.anio}`, "normal", "bajo_p10", "alto_p90"], ...c.map((p) => [p.dia, p.acumulado, p.normal, p.bajo, p.alto])]) };
}

// 4. Barras horizontales: qué parte del fuego ocurre en cada franja de altitud.
function altitud(d) {
  const max = Math.max(...d.bandas.map((b) => b.parte)), x0 = 128, bh = (H - M.t - 10) / d.bandas.length;
  const bars = [...d.bandas].reverse().map((b, i) => {
    const y = M.t + i * bh, w = (W - x0 - 70) * b.parte / max;
    return `<text x="${x0 - 8}" y="${y + bh / 2 + 4}" text-anchor="end" fill="${TINTA}">${esc(b.banda)}</text>` +
      `<rect x="${x0}" y="${y + 8}" width="${w}" height="${bh - 16}" fill="${b.parte === max ? NARANJA : AZUL}"><title>${esc(tr("chart.bandTip", { b: b.banda, v: fmt(b.focos_armonizados) }))}</title></rect>` +
      `<text x="${x0 + w + 6}" y="${y + bh / 2 + 4}" fill="${TINTA}" font-weight="600">${Math.round(b.parte * 100)} %</text>`;
  }).join("");
  return { svg: frame(bars, d.en_simple),
           csv: csv([["franja", "desde_m", "hasta_m", "focos_armonizados", "parte", "celdas"], ...d.bandas.map((b) => [`"${b.banda}"`, b.desde_m ?? "", b.hasta_m ?? "", b.focos_armonizados, b.parte, b.celdas])]) };
}

function save(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function downloadCsv(text, name) { save(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }), name); }
// PNG al doble de tamaño (nítido en informes), a partir del mismo SVG.
function downloadPng(svg, name) {
  const img = new Image(), url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = W * 2; canvas.height = H * 2;
    canvas.getContext("2d").drawImage(img, 0, 0, W * 2, H * 2);
    URL.revokeObjectURL(url);
    canvas.toBlob((blob) => save(blob, name), "image/png");
  };
  img.src = url;
}

export { estacionalidad, ranking, acumulado, altitud, downloadCsv, downloadPng }
