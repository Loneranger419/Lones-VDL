<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Tabs from '#lib/components/ui/tabs/index.js';
	import * as Card from '#lib/components/ui/card/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { api, call, type Job } from '#lib/api/client.js';
	import { keys, queries, type JobQuery } from '#lib/api/queries.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import AddDownloadForm from '#lib/components/app/add-download-form.svelte';
	import PolicyCard from '#lib/components/app/policy-card.svelte';
	import JobRow from '#lib/components/app/job-row.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import DownloadIcon from '@lucide/svelte/icons/download';
	import CircleCheckIcon from '@lucide/svelte/icons/circle-check';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';

	type Tab = 'active' | 'approval' | 'failed' | 'done';
	const TAB_QUERIES: Record<Tab, JobQuery> = {
		active: { status: ['queued', 'running'], limit: 200 },
		approval: { status: ['awaiting_approval'], limit: 200 },
		failed: { status: ['failed'], limit: 200 },
		done: { status: ['completed', 'cancelled'], limit: 100 }
	};

	const tab = $derived((page.url.searchParams.get('tab') as Tab) || 'active');
	const queryClient = useQueryClient();
	let url = $state('');

	const counts = createQuery(() => queries.jobCounts());
	const jobs = createQuery(() => queries.jobs(TAB_QUERIES[tab]));

	// Active: what runs now first, then the queue in the order it will run.
	const sorted = $derived.by(() => {
		const list = [...(jobs.data ?? [])];
		if (tab !== 'active') return list;
		return list.sort(
			(a, b) =>
				Number(b.status === 'running') - Number(a.status === 'running') ||
				b.priority - a.priority ||
				a.id - b.id
		);
	});

	const c = $derived(counts.data ?? {});
	const tabCount = $derived({
		active: (c.queued ?? 0) + (c.running ?? 0),
		approval: c.awaiting_approval ?? 0,
		failed: c.failed ?? 0,
		done: (c.completed ?? 0) + (c.cancelled ?? 0)
	});

	function setTab(value: string) {
		goto(value === 'active' ? '/downloads' : `/downloads?tab=${value}`, {
			replace: true,
			reset: false
		});
	}

	const bulk = createMutation(() => ({
		mutationFn: async (kind: 'retry' | 'clear') => {
			const targets: Job[] = jobs.data ?? [];
			const results = await Promise.allSettled(
				targets.map((job) => {
					const params = { params: { path: { job_id: job.id } } };
					return kind === 'retry'
						? call(api.POST('/api/jobs/{job_id}/retry', params))
						: call(api.DELETE('/api/jobs/{job_id}', params));
				})
			);
			return results.filter((r) => r.status === 'fulfilled').length;
		},
		onSuccess: (n, kind) => {
			queryClient.invalidateQueries({ queryKey: keys.jobs });
			toast.success(kind === 'retry' ? `Retrying ${n} jobs` : `Cleared ${n} jobs`);
		}
	}));
</script>

<PageHeader
	title="Downloads"
	description="Add videos, playlists, or channels and follow their progress."
/>

<p class="-mt-3 mb-6 rounded-lg bg-warning/10 px-3 py-2 text-sm">
	Downloads run one at a time, with daily limits and a short delay between videos, to avoid YouTube
	rate limits.
</p>

<div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
	<section class="order-2 min-w-0 xl:order-1">
		<Tabs.Root value={tab} onValueChange={setTab}>
			<div class="mb-3 flex flex-wrap items-center justify-between gap-2">
				<Tabs.List>
					<Tabs.Trigger value="active">
						Active {#if tabCount.active}<span class="ml-1 text-primary tabular-nums"
								>{tabCount.active}</span
							>{/if}
					</Tabs.Trigger>
					{#if tabCount.approval || tab === 'approval'}
						<Tabs.Trigger value="approval">
							Needs approval {#if tabCount.approval}<span class="ml-1 text-warning tabular-nums"
									>{tabCount.approval}</span
								>{/if}
						</Tabs.Trigger>
					{/if}
					<Tabs.Trigger value="failed">
						Failed {#if tabCount.failed}<span class="ml-1 text-brand-red tabular-nums"
								>{tabCount.failed}</span
							>{/if}
					</Tabs.Trigger>
					<Tabs.Trigger value="done">Finished</Tabs.Trigger>
				</Tabs.List>
				{#if tab === 'failed' && jobs.data?.length}
					<Button
						variant="outline"
						size="sm"
						onclick={() => bulk.mutate('retry')}
						disabled={bulk.isPending}
					>
						Retry all
					</Button>
				{:else if tab === 'done' && jobs.data?.length}
					<Button
						variant="outline"
						size="sm"
						onclick={() => bulk.mutate('clear')}
						disabled={bulk.isPending}
					>
						Clear list
					</Button>
				{/if}
			</div>
		</Tabs.Root>

		{#if tab === 'approval'}
			<p class="mb-3 text-sm text-muted-foreground">
				These videos need your personal account, for example because they are members-only. Nothing
				uses it until you approve a video, one at a time.
			</p>
		{/if}

		{#if jobs.isPending}
			<div class="space-y-2">
				{#each { length: 4 }, i (i)}<Skeleton class="h-16 w-full rounded-xl" />{/each}
			</div>
		{:else if sorted.length}
			<ul class="divide-y overflow-hidden rounded-xl border bg-card">
				{#each sorted as job (job.id)}
					<JobRow {job} />
				{/each}
			</ul>
			{#if tabCount[tab] > sorted.length}
				<p class="mt-3 text-center text-xs text-muted-foreground">
					Showing {sorted.length} of {tabCount[tab]}.
				</p>
			{/if}
		{:else if tab === 'active'}
			<EmptyState
				icon={DownloadIcon}
				title="Nothing downloading"
				description="Paste a link to start archiving. Channel auto-archive adds new uploads here automatically."
			/>
		{:else if tab === 'approval'}
			<EmptyState
				icon={CircleCheckIcon}
				title="Nothing to approve"
				description="Videos that need your personal account will wait here."
			/>
		{:else if tab === 'failed'}
			<EmptyState
				icon={CircleCheckIcon}
				title="No failures"
				description="Everything that was queued went through."
			/>
		{:else}
			<EmptyState icon={TriangleAlertIcon} title="No finished jobs yet" />
		{/if}
	</section>

	<aside class="order-1 space-y-6 xl:order-2">
		<Card.Root>
			<Card.Header>
				<Card.Title>Add to archive</Card.Title>
				<Card.Description>Video, playlist, or channel link.</Card.Description>
			</Card.Header>
			<Card.Content>
				<AddDownloadForm bind:url />
			</Card.Content>
		</Card.Root>
		<PolicyCard />
	</aside>
</div>
