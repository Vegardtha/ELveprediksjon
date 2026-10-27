import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Relativ base: siden fungerer både lokalt og under https://<bruker>.github.io/<repo>/
export default defineConfig({
  base: './',
  plugins: [react()],
})
