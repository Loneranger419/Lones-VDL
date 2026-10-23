/**
 * Caches the app shell so the installed app opens instantly (and shows its own UI when the
 * server is unreachable). API calls and media never touch the cache: they need the session
 * cookie, Range requests, and fresh data.
 */
import { version } from '$app/env';
import { assets, immutable } from '$app/manifest';
import { self as sw } from '$app/service-worker';

const CACHE = `lones-vdl-${version}`;
const SHELL = [...immutable, ...assets]
	.map((file) => `/${file.path.replace(/^\//, '')}`)
	.concat('/');

sw.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll(SHELL))
			.then(() => sw.skipWaiting())
	);
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
			.then(() => sw.clients.claim())
	);
});

sw.addEventListener('fetch', (event) => {
	const request = event.request;
	const url = new URL(request.url);
	if (request.method !== 'GET' || url.origin !== sw.location.origin) return;
	if (url.pathname.startsWith('/api/')) return;

	// Navigations: always try the network (new builds), fall back to the cached shell.
	if (request.mode === 'navigate') {
		event.respondWith(
			fetch(request).catch(async () => (await caches.match('/')) ?? Response.error())
		);
		return;
	}

	// Build assets are content-hashed: serve from cache, they never change.
	if (SHELL.includes(url.pathname)) {
		event.respondWith(caches.match(url.pathname).then((hit) => hit ?? fetch(request)));
	}
});
