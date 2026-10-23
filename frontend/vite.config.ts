import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev server proxies the API to the backend (`uv run lones-vdl serve --reload`).
const apiTarget = process.env.LONES_VDL_API_URL ?? 'http://127.0.0.1:8080';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// SPA: FastAPI serves build/ and falls back to index.html for client-side routes.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		proxy: {
			'/api': { target: apiTarget, changeOrigin: true }
		}
	}
});
