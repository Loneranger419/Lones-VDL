<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import * as Tabs from '#lib/components/ui/tabs/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { queries } from '#lib/api/queries.js';
	import { ago, bytes } from '#lib/format.js';
	import { ui } from '#lib/ui-state.svelte.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import ChannelAvatar from '#lib/components/app/channel-avatar.svelte';
	import CreatorDialog from '#lib/components/app/creator-dialog.svelte';
	import TvIcon from '@lucide/svelte/icons/tv';
	import UsersIcon from '@lucide/svelte/icons/users';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import RadarIcon from '@lucide/svelte/icons/radar';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';

	const tab = $derived(page.url.searchParams.get('tab') === 'creators' ? 'creators' : 'channels');
	const channels = createQuery(() => queries.channels());
	const creators = createQuery(() => ({ ...queries.creators(), enabled: tab === 'creators' }));
	let newCreator = $state(false);

	const sorted = $derived(
		[...(channels.data ?? [])].sort((a, b) =>
			(a.name ?? a.handle ?? '').localeCompare(b.name ?? b.handle ?? '')
		)
	);
	const watching = $derived(sorted.filter((c) => c.watch_enabled).length);
</script>

<PageHeader
	title={tab === 'creators' ? 'Creators' : 'Channels'}
	description={tab === 'creators'
		? 'People or brands, linking their channels across platforms.'
		: channels.data
			? `${channels.data.length} archived · ${watching} auto-archiving`
			: undefined}
>
	{#snippet actions()}
		{#if tab === 'creators'}
			<Button onclick={() => (newCreator = true)}><PlusIcon /> New creator</Button>
		{:else}
			<Button onclick={() => ui.openAdd()}><PlusIcon /> Add channel</Button>
		{/if}
	{/snippet}
</PageHeader>

<Tabs.Root
	value={tab}
	onValueChange={(v) =>
		goto(v === 'creators' ? '/channels?tab=creators' : '/channels', { replace: true })}
	class="mb-5"
>
	<Tabs.List>
		<Tabs.Trigger value="channels"><TvIcon /> Channels</Tabs.Trigger>
		<Tabs.Trigger value="creators"><UsersIcon /> Creators</Tabs.Trigger>
	</Tabs.List>
</Tabs.Root>

{#if tab === 'channels'}
	{#if channels.isPending}
		<div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,18rem),1fr))] gap-3">
			{#each { length: 6 }, i (i)}<Skeleton class="h-24 rounded-xl" />{/each}
		</div>
	{:else if !sorted.length}
		<EmptyState
			icon={TvIcon}
			title="No channels yet"
			description="Channels appear here when you archive their videos. Add a channel link to archive its uploads and keep it up to date."
		>
			<Button onclick={() => ui.openAdd()}>Add a channel</Button>
		</EmptyState>
	{:else}
		<div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,18rem),1fr))] gap-3">
			{#each sorted as channel (channel.id)}
				<a
					href="/channels/{channel.id}"
					class="group flex items-center gap-4 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40"
				>
					<ChannelAvatar {channel} class="size-14 text-base" />
					<div class="min-w-0 flex-1 space-y-1">
						<p class="truncate font-medium group-hover:text-primary">
							{channel.name ?? channel.handle}
						</p>
						<p class="truncate text-xs text-muted-foreground">
							{channel.video_count}
							{channel.video_count === 1 ? 'video' : 'videos'} · {bytes(channel.total_size)}
						</p>
						{#if channel.last_check_error}
							<p class="flex items-center gap-1 text-xs text-brand-red">
								<TriangleAlertIcon class="size-3" /> Last check failed
							</p>
						{:else if channel.watch_enabled}
							<p class="flex items-center gap-1 text-xs text-primary">
								<RadarIcon class="size-3" /> Auto-archive
								{#if channel.last_checked_at}<span class="text-muted-foreground"
										>· checked {ago(channel.last_checked_at)}</span
									>{/if}
							</p>
						{/if}
					</div>
				</a>
			{/each}
		</div>
	{/if}
{:else if creators.isPending}
	<div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,18rem),1fr))] gap-3">
		{#each { length: 3 }, i (i)}<Skeleton class="h-24 rounded-xl" />{/each}
	</div>
{:else if !creators.data?.length}
	<EmptyState
		icon={UsersIcon}
		title="No creators yet"
		description="A creator groups the channels one person runs, for example their main channel and a clips channel, or later their Twitch channel."
	>
		<Button onclick={() => (newCreator = true)}>New creator</Button>
	</EmptyState>
{:else}
	<div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,18rem),1fr))] gap-3">
		{#each creators.data as creator (creator.id)}
			<a
				href="/creators/{creator.id}"
				class="group space-y-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40"
			>
				<div>
					<p class="truncate font-medium group-hover:text-primary">{creator.name}</p>
					<p class="text-xs text-muted-foreground">
						{creator.channels.length}
						{creator.channels.length === 1 ? 'channel' : 'channels'} · {creator.video_count}
						{creator.video_count === 1 ? 'video' : 'videos'}
					</p>
				</div>
				<div class="flex -space-x-2">
					{#each creator.channels.slice(0, 6) as channel (channel.id)}
						<ChannelAvatar {channel} class="size-8 ring-2 ring-card" />
					{/each}
				</div>
			</a>
		{/each}
	</div>
{/if}

<CreatorDialog bind:open={newCreator} />
