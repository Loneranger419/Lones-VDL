/**
 * Typed API client. Types come from `schema.d.ts`, generated from the backend's OpenAPI schema
 * (`npm run api`), so a backend change that breaks the UI fails `svelte-check`.
 */
import createClient, { type Middleware } from 'openapi-fetch';
import type { components, paths } from './schema.js';

export type Schemas = components['schemas'];
export type Job = Schemas['JobOut'];
/** SSE-only event (`job.progress`), so not part of the OpenAPI schema. Mirrors JobProgress. */
export type JobProgress = {
	id: number;
	stage: string;
	progress: number | null;
	downloaded_bytes?: number | null;
	total_bytes?: number | null;
	speed?: number | null;
	eta?: number | null;
};
export type Video = Schemas['VideoOut'];
export type VideoDetail = Schemas['VideoDetail'];
export type VideoPage = Schemas['VideoPage'];
export type Channel = Schemas['ChannelDetail'];
export type ChannelBrief = Schemas['ChannelOut'];
export type Creator = Schemas['CreatorOut'];
export type Collection = Schemas['CollectionOut'];
export type CollectionDetail = Schemas['CollectionDetail'];
export type CookieStatus = Schemas['CookieStatus'];
export type Account = Schemas['AccountOut'];
export type PolicyStatus = Schemas['PolicyStatus'];
export type CookieHealth = Schemas['CookieHealth'];
export type Stats = Schemas['StatsOut'];
export type DoctorReport = Schemas['DoctorReport'];
export type YtdlpStatus = Schemas['YtdlpStatus'];
export type RuntimeSettings = Schemas['RuntimeSettings'];
export type FilterPreset = Schemas['PresetOut'];
export type TagCount = Schemas['TagOut'];

/** An API error with the server's message (FastAPI `detail`) and error kind, if any. */
export class ApiError extends Error {
	constructor(
		readonly status: number,
		message: string,
		readonly body: Record<string, unknown> = {}
	) {
		super(message);
	}

	get kind(): string | undefined {
		return typeof this.body.kind === 'string' ? this.body.kind : undefined;
	}
}

let onUnauthorized: () => void = () => {};

/** Called once by the app shell: where to go when the session has expired. */
export function setUnauthorizedHandler(handler: () => void) {
	onUnauthorized = handler;
}

const authRedirect: Middleware = {
	onResponse({ request, response }) {
		if (response.status === 401 && !new URL(request.url).pathname.startsWith('/api/auth/')) {
			onUnauthorized();
		}
	}
};

// Same origin: the backend serves the UI. The header is the server's CSRF guard.
export const api = createClient<paths>({ headers: { 'x-lones-vdl': '1' } });
api.use(authRedirect);

function message(detail: unknown, status: number): string {
	if (typeof detail === 'string') return detail;
	if (Array.isArray(detail) && detail.length) {
		// Pydantic validation errors: [{loc, msg}, ...]
		return detail
			.map((d) => (typeof d?.msg === 'string' ? d.msg.replace(/^Value error, /, '') : ''))
			.filter(Boolean)
			.join('; ');
	}
	return `Request failed (${status})`;
}

/** Unwrap an openapi-fetch result: return data or throw an ApiError. */
export async function call<T>(
	request: Promise<{ data?: T; error?: unknown; response: Response }>
): Promise<T> {
	const { data, error, response } = await request;
	if (error !== undefined || !response.ok) {
		const body = (error && typeof error === 'object' ? error : {}) as Record<string, unknown>;
		throw new ApiError(response.status, message(body.detail ?? error, response.status), body);
	}
	return data as T;
}

export function errorMessage(error: unknown): string {
	if (error instanceof Error) return error.message;
	return String(error);
}

/** URLs for media the browser loads directly (session cookie authenticates them). */
export const mediaUrl = {
	chapters: (id: number) => `/api/videos/${id}/chapters.vtt`,
	video: (id: number) => `/api/videos/${id}/media`,
	thumbnail: (id: number) => `/api/videos/${id}/thumbnail`,
	subtitle: (id: number, lang: string) => `/api/videos/${id}/subtitles/${lang}.vtt`,
	avatar: (id: number) => `/api/channels/${id}/avatar`,
	banner: (id: number) => `/api/channels/${id}/banner`
};
