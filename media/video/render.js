// Uso: node render.js <dir> keyframes   |   node render.js <dir> all
const { chromium } = require('playwright')
const path = require('path'), fs = require('fs')
const dir = process.argv[2], mode = process.argv[3] || 'keyframes'
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  await p.goto('file://' + path.join(dir, 'index.html'))
  await p.evaluate(() => document.fonts.ready)
  const canvas = await p.$('canvas')
  if (mode === 'keyframes') {
    for (const t of [2, 7.5, 11, 14.8, 19.5, 24.5, 28.5]) {
      await p.evaluate((t) => window.render(t), t)
      await canvas.screenshot({ path: path.join(dir, `kf_${t}.png`) })
    }
  } else {
    const fr = path.join(dir, 'frames'); fs.mkdirSync(fr, { recursive: true })
    const FPS = 30, N = 30 * FPS
    for (let i = 0; i < N; i++) {
      await p.evaluate((t) => window.render(t), i / FPS)
      await canvas.screenshot({ path: path.join(fr, `f${String(i).padStart(4, '0')}.png`) })
    }
  }
  await b.close()
})()
