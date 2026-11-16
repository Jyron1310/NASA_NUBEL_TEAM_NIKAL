import React from 'react'
import ReactDOM from 'react-dom/client'
import 'maplibre-gl/dist/maplibre-gl.css'
import './fire-map.css'
import './firecal.css'
import './nikal-paleta.css'
import './nikal.css'
import './panel-historia.css'
import './ambitos-dias.css'
import './paneles.css'
import './snake.css'
import './tutorial.css'
import './welcome.css'
import './capas.css'
import App from './FireMapApp.jsx'
import { getLang, setLang } from './i18n.js'

setLang(getLang())          // fija <html lang> y el título según el idioma inicial

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
