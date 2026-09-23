import './styles/tokens.css'
import './styles/base.css'
import './App.css'
import './pages/ConsensusPage.css'
import './styles/shared.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { installAccessCodeInterceptors } from './accessCode'

// Must run before any component issues a request, so every call carries the code.
installAccessCodeInterceptors()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
