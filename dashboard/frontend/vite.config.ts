import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import type { Connect, Plugin } from 'vite';
import { fileURLToPath } from 'url';

const API_BASE = process.env.API_BASE ?? 'http://localhost:8080';

// Silently absorb any /api/v2/* requests (e.g. OpenCode UI health-checks)
// so they don't show as 404s in either the Vite or uvicorn logs.
const ignoreApiV2: Connect.NextHandleFunction = (req, res, next) => {
	if (req.url?.startsWith('/api/v2/')) {
		res.writeHead(200, { 'Content-Type': 'application/json' });
		res.end('{}');
		return;
	}
	next();
};

const ignoreApiV2Plugin: Plugin = {
	name: 'ignore-api-v2',
	configureServer(server) {
		server.middlewares.use(ignoreApiV2);
	}
};

export default defineConfig({
	plugins: [sveltekit(), ignoreApiV2Plugin],
	server: {
		fs: {
			// Allow the bird-detector project root so JSON data files (e.g.
			// uk_species_filter.json) can be imported from components.
			allow: [fileURLToPath(new URL('../..', import.meta.url))]
		},
		proxy: {
			'/api/v1': API_BASE,
			'/stream': { target: API_BASE, changeOrigin: true },
			'/audio': API_BASE,
			'/spectrogram': API_BASE,
			'/healthz': API_BASE
		}
	}
});
