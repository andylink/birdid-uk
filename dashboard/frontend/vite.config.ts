import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { fileURLToPath } from 'url';

const API_BASE = process.env.API_BASE ?? 'http://localhost:8080';

export default defineConfig({
	plugins: [sveltekit()],
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
