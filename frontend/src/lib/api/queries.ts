/** Query keys and fetchers, shared by pages and by the live-update handler. */
import { infiniteQueryOptions, queryOptions } from '@tanstack/svelte-query';
import { api, call } from './client.js';
import type { paths } from './schema.js';

export type VideoQuery = NonNullable<paths['/api/videos']['get']['parameters']['query']>;
export type JobQuery = NonNullable<paths['/api/jobs']['get']['parameters']['query']>;

export const PAGE_SIZE = 48;

export const keys = {
	auth: ['auth'] as const,
	jobs: ['jobs'] as const,
	jobList: (query: JobQuery) => ['jobs', 'list', query] as const,
	jobCounts: ['jobs', 'counts'] as const,
	videos: ['videos'] as const,
	videoList: (query: VideoQuery) => ['videos', 'list', query] as const,
	videoPages: (query: VideoQuery) => ['videos', 'pages', query] as const,
	video: (id: number) => ['videos', 'detail', id] as const,
	related: (id: number) => ['videos', 'related', id] as const,
	continueWatching: ['videos', 'continue'] as const,
	channels: ['channels'] as const,
	channel: (id: number) => ['channels', id] as const,
	creators: ['creators'] as const,
	creator: (id: number) => ['creators', id] as const,
	collections: ['collections'] as const,
	collection: (id: number) => ['collections', id] as const,
	cookies: ['cookies'] as const,
	stats: ['stats'] as const,
	ytdlp: ['ytdlp'] as const,
	settings: ['settings'] as const
};

export const queries = {
	auth: () =>
		queryOptions({
			queryKey: keys.auth,
			queryFn: () => call(api.GET('/api/auth/status')),
			staleTime: Infinity
		}),
	jobs: (query: JobQuery) =>
		queryOptions({
			queryKey: keys.jobList(query),
			queryFn: () => call(api.GET('/api/jobs', { params: { query } }))
		}),
	jobCounts: () =>
		queryOptions({
			queryKey: keys.jobCounts,
			queryFn: () => call(api.GET('/api/jobs/counts'))
		}),
	videos: (query: VideoQuery) =>
		queryOptions({
			queryKey: keys.videoList(query),
			queryFn: () => call(api.GET('/api/videos', { params: { query } }))
		}),
	/** Library grid: offset pages, loaded as the user scrolls. */
	videoPages: (query: Omit<VideoQuery, 'offset' | 'limit'>) =>
		infiniteQueryOptions({
			queryKey: keys.videoPages(query),
			queryFn: ({ pageParam }) =>
				call(
					api.GET('/api/videos', {
						params: { query: { ...query, offset: pageParam, limit: PAGE_SIZE } }
					})
				),
			initialPageParam: 0,
			getNextPageParam: (last) =>
				last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined
		}),
	video: (id: number) =>
		queryOptions({
			queryKey: keys.video(id),
			queryFn: () => call(api.GET('/api/videos/{video_pk}', { params: { path: { video_pk: id } } }))
		}),
	related: (id: number) =>
		queryOptions({
			queryKey: keys.related(id),
			queryFn: () =>
				call(api.GET('/api/videos/{video_pk}/related', { params: { path: { video_pk: id } } }))
		}),
	continueWatching: () =>
		queryOptions({
			queryKey: keys.continueWatching,
			queryFn: () => call(api.GET('/api/videos/continue'))
		}),
	channels: () =>
		queryOptions({
			queryKey: keys.channels,
			queryFn: () => call(api.GET('/api/channels'))
		}),
	channel: (id: number) =>
		queryOptions({
			queryKey: keys.channel(id),
			queryFn: () =>
				call(api.GET('/api/channels/{channel_pk}', { params: { path: { channel_pk: id } } }))
		}),
	creators: () =>
		queryOptions({
			queryKey: keys.creators,
			queryFn: () => call(api.GET('/api/creators'))
		}),
	creator: (id: number) =>
		queryOptions({
			queryKey: keys.creator(id),
			queryFn: () =>
				call(api.GET('/api/creators/{creator_pk}', { params: { path: { creator_pk: id } } }))
		}),
	collections: () =>
		queryOptions({
			queryKey: keys.collections,
			queryFn: () => call(api.GET('/api/collections'))
		}),
	collection: (id: number) =>
		queryOptions({
			queryKey: keys.collection(id),
			queryFn: () =>
				call(
					api.GET('/api/collections/{collection_pk}', {
						params: { path: { collection_pk: id } }
					})
				)
		}),
	cookies: () =>
		queryOptions({
			queryKey: keys.cookies,
			queryFn: () => call(api.GET('/api/cookies'))
		}),
	stats: () =>
		queryOptions({
			queryKey: keys.stats,
			queryFn: () => call(api.GET('/api/system/stats'))
		}),
	ytdlp: () =>
		queryOptions({
			queryKey: keys.ytdlp,
			queryFn: () => call(api.GET('/api/system/ytdlp'))
		}),
	settings: () =>
		queryOptions({
			queryKey: keys.settings,
			queryFn: () => call(api.GET('/api/settings'))
		})
};
