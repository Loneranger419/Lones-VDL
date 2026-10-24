/**
 * Live updates from `GET /api/events` (Server-Sent Events). Job state changes patch the
 * cached job lists in place; download progress lives in `live.progress` so progress bars
 * update many times a second without refetching anything.
 */
import type { QueryClient } from '@tanstack/svelte-query';
import type { Job, JobProgress } from './client.js';
import { keys } from './queries.js';

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
// Moves a job between the Downloads tabs, and changes the policy's counts.
const SETTLED = new Set([...TERMINAL, 'awaiting_approval']);

class LiveState {
	connected = $state(false);
	progress = $state<Record<number, JobProgress>>({});
}

export const live = new LiveState();

export function connectEvents(client: QueryClient): () => void {
	const pending = new Map<string, readonly unknown[]>();
	let timer: ReturnType<typeof setTimeout> | undefined;

	// Coalesce invalidations: a channel backfill can emit hundreds of events per second.
	function invalidateSoon(...queryKeys: (readonly unknown[])[]) {
		for (const key of queryKeys) pending.set(JSON.stringify(key), key);
		timer ??= setTimeout(() => {
			for (const key of pending.values()) client.invalidateQueries({ queryKey: key });
			pending.clear();
			timer = undefined;
		}, 400);
	}

	function patchJob(job: Job) {
		let found = false;
		client.setQueriesData<Job[]>({ queryKey: ['jobs', 'list'] }, (list) => {
			if (!Array.isArray(list)) return list;
			if (!list.some((j) => j.id === job.id)) return list;
			found = true;
			return list.map((j) => (j.id === job.id ? job : j));
		});
		// New jobs, or jobs that changed status and so move between filtered lists.
		if (!found || SETTLED.has(job.status)) invalidateSoon(keys.jobs);
		else invalidateSoon(keys.jobCounts, keys.jobQueue);
	}

	const source = new EventSource('/api/events');
	function on<T>(type: string, handler: (data: T) => void) {
		source.addEventListener(type, (event) => handler(JSON.parse((event as MessageEvent).data)));
	}

	on('hello', () => {
		live.connected = true;
		// Anything may have changed while disconnected.
		invalidateSoon(keys.jobs, keys.videos, keys.channels);
	});
	on('job', (job: Job) => {
		if (job.status !== 'running') delete live.progress[job.id];
		patchJob(job);
		if (SETTLED.has(job.status)) invalidateSoon(keys.policy, keys.accounts);
		if (job.kind === 'expand' && TERMINAL.has(job.status)) invalidateSoon(keys.channels);
		if (job.kind === 'verify' || job.kind === 'rescan') invalidateSoon(keys.videos, keys.stats);
		if ((job.kind === 'subtitles' || job.kind === 'chapters') && TERMINAL.has(job.status))
			invalidateSoon(keys.videos);
	});
	on('job.progress', (progress: JobProgress) => {
		live.progress[progress.id] = progress;
	});
	on('job.removed', () => invalidateSoon(keys.jobs));
	on('jobs.added', () => invalidateSoon(keys.jobs));
	on('video', () => invalidateSoon(keys.videos, keys.channels, keys.stats, keys.creators));
	on('video.removed', () => invalidateSoon(keys.videos, keys.channels, keys.stats));
	on('ytdlp', (status: unknown) => client.setQueryData(keys.ytdlp, status));
	source.onerror = () => {
		live.connected = false; // EventSource reconnects on its own
	};

	return () => {
		source.close();
		clearTimeout(timer);
		live.connected = false;
	};
}
