import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    // Service worker versiyasi (src/lib/pwa.ts): deployda git commit
    // (deploy/server-pull.sh APP_VERSION beradi), aks holda build vaqti.
    __APP_BUILD_ID__: JSON.stringify(process.env.APP_VERSION || new Date().toISOString()),
  },
  optimizeDeps: {
    exclude: ['pdfjs-dist'],
  },
})
