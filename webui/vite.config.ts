import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The build output lands directly inside the installed Python package
// (src/chronicle/webui_dist), so `pip install`/`pipx install` carries the
// built UI with it -- no separate asset-copy step at install time.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../src/chronicle/webui_dist',
    emptyOutDir: true,
  },
  server: {
    // During `npm run dev`, proxy API calls to the daemon's FastAPI server
    // (started by `chronicle daemon start`, default port 4317) so the UI
    // can be developed live against real data.
    proxy: {
      '/api': 'http://127.0.0.1:4317',
    },
  },
})
