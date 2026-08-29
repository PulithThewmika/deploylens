import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Body font (Inter) and heading font (Mohave), self-hosted via
// @fontsource rather than a Google Fonts <link> — no runtime network
// dependency, no FOUC.
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/mohave/400.css'
import '@fontsource/mohave/500.css'
import '@fontsource/mohave/600.css'
import '@fontsource/mohave/700.css'

import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
