# Nikal video (30 s)

`../nikal_video_30s.mp4`: 1920×1080, 30 fps, no audio, Spanish captions. Built from the real data in `data/harmonized/`.

How to regenerate it:
1. Generate `data.js` (raw and harmonized yearly series, monthly matrix, 2020 hotspots and the Cusco boundary) from
   `data/harmonized/*.csv` and `harmonizacion/cusco_ref/limite.json` (global variable `window.D`).
2. `node render.js <this folder> all` (Playwright) writes 900 frames to `frames/`.
3. `ffmpeg -framerate 30 -i frames/f%04d.png -c:v libx264 -pix_fmt yuv420p -crf 20 nikal_video_30s.mp4`
