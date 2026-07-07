import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwind from '@astrojs/tailwind';

// In development the API runs on :8000 and is proxied, so the browser only ever talks to one origin.
export default defineConfig({
  integrations: [react(), tailwind({ applyBaseStyles: false })],
  server: { port: 4321 },
  vite: { server: { proxy: { '/api': 'http://127.0.0.1:8000' } } },
});
