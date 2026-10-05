import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './lib/auth.tsx'
import { PermissionsProvider } from './lib/permissions.tsx'
import ErrorBoundary from './components/ErrorBoundary.tsx'
import { ToastProvider } from './components/ui/Toast.tsx'
import ForcedTwoFactor from './components/admin/ForcedTwoFactor.tsx'
import { registerServiceWorker, watchForNewVersion } from './lib/pwa.ts'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <PermissionsProvider>
            <ToastProvider>
              <App />
              <ForcedTwoFactor />
            </ToastProvider>
          </PermissionsProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
)

// O'rnatiladigan ilova (PWA) — faqat production build'da.
registerServiceWorker()
watchForNewVersion()
