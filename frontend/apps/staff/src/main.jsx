import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '../../../src/styles/global.css'
import StaffApp from '../../../src/app/StaffApp.jsx'
import '../../../src/app/theme/branding.css'
import '../../../src/styles/product-shell.css'
import '../../../src/styles/dashboard-polish.css'
import '../../../src/styles/dashboard-controls.css'
import '../../../src/styles/dashboard-shell.css'
import '../../../src/styles/scrollbars.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter basename = "/staff">
      <StaffApp />
    </BrowserRouter>
  </StrictMode>,
)
