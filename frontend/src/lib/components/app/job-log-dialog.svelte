<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { api, call, type Job } from '#lib/api/client.js';
	import RefreshIcon from '@lucide/svelte/icons/refresh-cw';

	let { job, open = $bindable(false) }: { job: Job; open?: boolean } = $props();

	const log = createQuery(() => ({
		queryKey: ['jobs', 'log', job.id],
		queryFn: () =>
			call(
				api.GET('/api/jobs/{job_id}/log', {
					params: { path: { job_id: job.id } },
					parseAs: 'text'
				})
			) as Promise<string>,
		enabled: open,
		refetchInterval: job.status === 'running' ? 2000 : false,
		staleTime: 0
	}));

	let pre = $state<HTMLPreElement>();
	$effect(() => {
		if (log.data !== undefined && pre) pre.scrollTop = pre.scrollHeight;
	});
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="flex max-h-[85svh] flex-col sm:max-w-4xl">
		<Dialog.Header>
			<Dialog.Title class="truncate pr-6">Log · {job.title ?? job.url}</Dialog.Title>
			<Dialog.Description>
				Full yt-dlp output for job #{job.id}. Useful when reporting or debugging a failure.
			</Dialog.Description>
		</Dialog.Header>
		<pre
			bind:this={pre}
			class="min-h-48 flex-1 overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-relaxed break-all whitespace-pre-wrap">{log.isPending
				? 'Loading…'
				: log.data || 'No log yet.'}</pre>
		<Dialog.Footer>
			<Button variant="outline" onclick={() => log.refetch()} disabled={log.isFetching}>
				<RefreshIcon class={log.isFetching ? 'animate-spin' : ''} /> Refresh
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
