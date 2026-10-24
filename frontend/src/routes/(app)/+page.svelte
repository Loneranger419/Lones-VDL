<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { queries } from '#lib/api/queries.js';
	import { live } from '#lib/api/events.svelte.js';
	import { ui } from '#lib/ui-state.svelte.js';
	import VideoCard from '#lib/components/app/video-card.svelte';
	import VideoGrid from '#lib/components/app/video-grid.svelte';
	import ChannelAvatar from '#lib/components/app/channel-avatar.svelte';
	import Logo from '#lib/components/app/logo.svelte';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import DownloadIcon from '@lucide/svelte/icons/download';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import KeyRoundIcon from '@lucide/svelte/icons/key-round';

	const continueWatching = createQuery(() => queries.continueWatching());
	const recent = createQuery(() => queries.videos({ sort: 'archived_desc', limit: 12 }));
	const channels = createQuery(() => queries.channels());
	const active = createQuery(() => queries.jobs({ status: ['running'], limit: 5 }));
	const counts = createQuery(() => queries.jobCounts());

	const queued = $derived((counts.data?.queued ?? 0) + (counts.data?.running ?? 0));
	const empty = $derived(recent.isSuccess && recent.data.total === 0);
	const topChannels = $derived(
		[...(channels.data ?? [])].sort((a, b) => b.video_count - a.video_count).slice(0, 12)
	);
</script>

<svelte:head><title>Home · Lones-VDL</title></svelte:head>

{#snippet heading(title: string, href?: string, label = 'See all')}
	<div class="mb-3 flex items-center justify-between gap-2">
		<h2 class="text-lg font-semibold tracking-tight">{title}</h2>
		{#if href}
			<a {href} class="flex items-center text-sm text-muted-foreground hover:text-foreground">
				{label}<ChevronRightIcon class="size-4" />
			</a>
		{/if}
	</div>
{/snippet}

{#if empty}
	<section
		class="relative mx-auto mt-6 max-w-2xl overflow-hidden rounded-3xl border bg-gradient-to-br from-primary/15 via-card to-card p-8 text-center sm:p-12"
	>
		<Logo class="mx-auto mb-5 size-14" />
		<h1 class="text-2xl font-semibold tracking-tight sm:text-3xl">Welcome to your archive</h1>
		<p class="mx-auto mt-2 max-w-md text-muted-foreground">
			Save videos, playlists, and whole channels to your own storage, and watch them here.
		</p>
		<div class="mt-6 flex flex-wrap justify-center gap-2">
			<Button size="lg" onclick={() => ui.openAdd()}><PlusIcon /> Add your first download</Button>
			<Button size="lg" variant="outline" href="/health#accounts"
				><KeyRoundIcon /> YouTube accounts</Button
			>
		</div>
		<p class="mt-5 text-xs text-muted-foreground">
			Most public videos download without signing in. Age-restricted ones need a dedicated YouTube
			account, which you can add any time.
		</p>
	</section>
{:else}
	<div class="space-y-10">
		{#if queued}
			<a
				href="/downloads"
				class="flex items-center gap-3 rounded-xl border bg-card p-3 pr-4 transition-colors hover:border-primary/40"
			>
				<span class="grid size-9 place-items-center rounded-lg bg-primary/15 text-primary">
					<DownloadIcon class="size-4" />
				</span>
				<div class="min-w-0 flex-1">
					<p class="text-sm font-medium">
						{queued}
						{queued === 1 ? 'download' : 'downloads'} in progress
					</p>
					{#each active.data?.slice(0, 1) ?? [] as job (job.id)}
						{@const progress = live.progress[job.id]?.progress ?? job.progress ?? 0}
						<p class="truncate text-xs text-muted-foreground">
							{job.title ?? job.url}{progress ? ` · ${(progress * 100).toFixed(0)}%` : ''}
						</p>
					{/each}
				</div>
				<ChevronRightIcon class="size-4 text-muted-foreground" />
			</a>
		{/if}

		{#if continueWatching.data?.length}
			<section>
				{@render heading('Continue watching', '/library?watch=in_progress&sort=watched_desc')}
				<div
					class="-mx-4 flex snap-x snap-mandatory [scrollbar-width:thin] gap-4 overflow-x-auto px-4 pb-2 md:mx-0 md:px-0"
				>
					{#each continueWatching.data as video (video.id)}
						<div class="w-64 shrink-0 snap-start sm:w-72">
							<VideoCard {video} />
						</div>
					{/each}
				</div>
			</section>
		{/if}

		<section>
			{@render heading('Recently archived', '/library')}
			{#if recent.isPending}
				<VideoGrid videos={[]} loading skeletons={8} />
			{:else}
				<VideoGrid videos={recent.data?.items ?? []} />
			{/if}
		</section>

		{#if channels.isPending}
			<Skeleton class="h-24 w-full rounded-xl" />
		{:else if topChannels.length}
			<section>
				{@render heading('Channels', '/channels')}
				<div
					class="-mx-4 flex [scrollbar-width:thin] gap-5 overflow-x-auto px-4 pb-2 md:mx-0 md:px-0"
				>
					{#each topChannels as channel (channel.id)}
						<a
							href="/channels/{channel.id}"
							class="group flex w-20 shrink-0 flex-col items-center gap-2 text-center"
						>
							<ChannelAvatar
								{channel}
								class="size-16 text-base ring-2 ring-transparent transition group-hover:ring-primary"
							/>
							<span class="line-clamp-2 text-xs group-hover:text-primary"
								>{channel.name ?? channel.handle}</span
							>
						</a>
					{/each}
				</div>
			</section>
		{/if}
	</div>
{/if}
