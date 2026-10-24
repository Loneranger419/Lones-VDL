<script lang="ts">
	import { page } from '$app/state';
	import {
		createInfiniteQuery,
		createMutation,
		createQuery,
		useQueryClient
	} from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Card from '#lib/components/ui/card/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Switch } from '#lib/components/ui/switch/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import * as ToggleGroup from '#lib/components/ui/toggle-group/index.js';
	import { api, call, errorMessage, mediaUrl, type Schemas } from '#lib/api/client.js';
	import { keys, queries, type VideoQuery } from '#lib/api/queries.js';
	import { ago, bytes, QUALITY_LABELS } from '#lib/format.js';
	import { onVisible } from '#lib/attachments.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import VideoGrid from '#lib/components/app/video-grid.svelte';
	import ChannelAvatar from '#lib/components/app/channel-avatar.svelte';
	import SimpleSelect from '#lib/components/app/simple-select.svelte';
	import ConfirmDialog from '#lib/components/app/confirm-dialog.svelte';
	import CreatorDialog from '#lib/components/app/creator-dialog.svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import HiddenNotice from '#lib/components/app/hidden-notice.svelte';
	import RefreshIcon from '@lucide/svelte/icons/refresh-cw';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import TvIcon from '@lucide/svelte/icons/tv';
	import FilmIcon from '@lucide/svelte/icons/film';

	const id = $derived(Number(page.params.id));
	const queryClient = useQueryClient();

	const channel = createQuery(() => queries.channel(id));
	const creators = createQuery(() => queries.creators());
	const settings = createQuery(() => queries.settings());
	const c = $derived(channel.data?.id === id ? channel.data : undefined);

	// --- Videos ----------------------------------------------------------------------------
	let sort = $state<NonNullable<VideoQuery['sort']>>('uploaded_desc');
	let kind = $state('all');
	// The default tag preset hides some videos; this shows them again for this visit.
	let showHidden = $state(false);
	const presets = createQuery(() => queries.presets());
	const presetName = $derived(
		presets.data?.presets.find((p) => p.id === presets.data?.default_id)?.name ?? ''
	);
	const videos = createInfiniteQuery(() =>
		queries.videoPages({
			channel: id,
			sort,
			preset: showHidden ? 'none' : 'default',
			kind: kind === 'all' ? undefined : (kind as VideoQuery['kind'])
		})
	);
	const items = $derived(videos.data?.pages.flatMap((p) => p.items) ?? []);
	function more() {
		if (videos.hasNextPage && !videos.isFetchingNextPage) videos.fetchNextPage();
	}

	// --- Settings --------------------------------------------------------------------------
	type ChannelChanges = Partial<Schemas['ChannelUpdate']>;
	const update = createMutation(() => ({
		mutationFn: (changes: ChannelChanges) =>
			call(
				api.PATCH('/api/channels/{channel_pk}', {
					params: { path: { channel_pk: id } },
					body: { backfill: false, ...changes }
				})
			),
		onSuccess: (saved) => {
			queryClient.setQueryData(keys.channel(id), saved);
			queryClient.invalidateQueries({ queryKey: keys.channels });
			queryClient.invalidateQueries({ queryKey: keys.creators });
			queryClient.invalidateQueries({ queryKey: keys.jobs });
		},
		onError: (e) => toast.error(e.message)
	}));

	const check = createMutation(() => ({
		mutationFn: () =>
			call(api.POST('/api/channels/{channel_pk}/check', { params: { path: { channel_pk: id } } })),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: keys.jobs });
			toast.success('Checking for new uploads', {
				description: 'New videos will be queued automatically.'
			});
		},
		onError: (e) => toast.error(e.message)
	}));

	// Turning auto-archive on asks whether to also fetch the back catalogue.
	let confirmWatch = $state(false);
	let backfill = $state(false);
	function setWatch(on: boolean) {
		if (on) {
			backfill = false;
			confirmWatch = true;
		} else {
			update.mutate({ watch_enabled: false });
		}
	}

	const tabs = $derived(
		c
			? ([
					c.watch_videos && 'videos',
					c.watch_streams && 'streams',
					c.watch_shorts && 'shorts'
				].filter(Boolean) as string[])
			: []
	);
	function setTabs(value: string[]) {
		if (!value.length) return; // at least one
		update.mutate({
			watch_videos: value.includes('videos'),
			watch_streams: value.includes('streams'),
			watch_shorts: value.includes('shorts')
		});
	}

	const qualityOptions = $derived([
		{
			value: 'default',
			label: `Default (${QUALITY_LABELS[settings.data?.current.default_quality ?? 'best']})`
		},
		...Object.entries(QUALITY_LABELS).map(([value, label]) => ({ value, label }))
	]);

	let newCreator = $state(false);
	const creatorOptions = $derived([
		{ value: 'none', label: 'No creator' },
		...(creators.data ?? []).map((cr) => ({ value: String(cr.id), label: cr.name })),
		{ value: 'new', label: 'New creator…' }
	]);
	function setCreator(value: string) {
		if (value === 'new') newCreator = true;
		else update.mutate({ creator_id: value === 'none' ? null : Number(value) });
	}

	let bannerFailed = $state(false);
</script>

<svelte:head><title>{c ? (c.name ?? c.handle) : 'Channel'} · Lones-VDL</title></svelte:head>

{#if channel.isError}
	<PageHeader title="Channel" />
	<EmptyState
		icon={TvIcon}
		title="Couldn't load this channel"
		description={errorMessage(channel.error)}
	>
		<Button variant="outline" href="/channels">All channels</Button>
	</EmptyState>
{:else if !c}
	<Skeleton class="mb-6 aspect-[6/1] w-full rounded-2xl" />
	<Skeleton class="h-16 w-1/2" />
{:else}
	{#if c.has_banner && !bannerFailed}
		<div class="-mx-4 mb-5 aspect-[6/1] overflow-hidden bg-muted sm:mx-0 sm:rounded-2xl">
			<img
				src={mediaUrl.banner(c.id)}
				alt=""
				class="size-full object-cover"
				onerror={() => (bannerFailed = true)}
			/>
		</div>
	{/if}

	<div class="mb-6 flex flex-wrap items-center gap-4">
		<ChannelAvatar channel={c} class="size-16 text-lg sm:size-20" />
		<div class="min-w-0 flex-1">
			<h1 class="truncate text-2xl font-semibold tracking-tight">{c.name ?? c.handle}</h1>
			<p class="text-sm text-muted-foreground">
				{#if c.handle}{c.handle} ·
				{/if}{c.video_count}
				{c.video_count === 1 ? 'video' : 'videos'} · {bytes(c.total_size)}
			</p>
		</div>
		{#if c.url}
			<Button variant="outline" href={c.url} target="_blank" rel="noopener noreferrer">
				<ExternalLinkIcon /> Open on YouTube
			</Button>
		{/if}
	</div>

	<div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
		<section class="order-2 min-w-0 xl:order-1">
			<div class="mb-4 flex flex-wrap items-center gap-2">
				<ToggleGroup.Root
					type="single"
					variant="outline"
					size="sm"
					value={kind}
					onValueChange={(v) => v && (kind = v)}
				>
					<ToggleGroup.Item value="all">All</ToggleGroup.Item>
					<ToggleGroup.Item value="video">Videos</ToggleGroup.Item>
					<ToggleGroup.Item value="stream">Streams</ToggleGroup.Item>
					<ToggleGroup.Item value="short">Shorts</ToggleGroup.Item>
				</ToggleGroup.Root>
				<div class="ml-auto">
					<SimpleSelect
						size="sm"
						class="w-40"
						label="Sort"
						value={sort}
						onchange={(v) => (sort = v as typeof sort)}
						options={[
							{ value: 'uploaded_desc', label: 'Newest' },
							{ value: 'uploaded_asc', label: 'Oldest' },
							{ value: 'archived_desc', label: 'Recently archived' },
							{ value: 'title', label: 'Title A–Z' }
						]}
					/>
				</div>
			</div>
			<div class="mb-3 empty:hidden">
				<HiddenNotice
					hidden={videos.data?.pages[0]?.hidden ?? 0}
					preset={presetName}
					onshow={() => (showHidden = true)}
				/>
			</div>
			{#if !videos.isPending && !items.length}
				<EmptyState
					icon={FilmIcon}
					title="No videos archived"
					description={kind === 'all'
						? 'Turn on auto-archive or use “Check now” to fetch this channel’s uploads.'
						: 'Nothing of this kind archived yet.'}
				/>
			{:else}
				<VideoGrid
					videos={items}
					showChannel={false}
					loading={videos.isPending || videos.isFetchingNextPage}
				/>
				{#if videos.hasNextPage && !videos.isFetchingNextPage}
					<div {@attach onVisible(more)} class="h-px"></div>
				{/if}
			{/if}
		</section>

		<aside class="order-1 space-y-4 xl:order-2">
			<Card.Root>
				<Card.Header>
					<Card.Title>Auto-archive</Card.Title>
					<Card.Description>Check regularly and download new uploads.</Card.Description>
					<Card.Action>
						<Switch
							checked={c.watch_enabled}
							onCheckedChange={setWatch}
							disabled={update.isPending}
							aria-label="Auto-archive"
						/>
					</Card.Action>
				</Card.Header>
				<Card.Content class="space-y-4">
					<div class="space-y-2">
						<Label>Include</Label>
						<ToggleGroup.Root
							type="multiple"
							variant="outline"
							size="sm"
							value={tabs}
							onValueChange={setTabs}
						>
							<ToggleGroup.Item value="videos">Videos</ToggleGroup.Item>
							<ToggleGroup.Item value="streams">Past streams</ToggleGroup.Item>
							<ToggleGroup.Item value="shorts">Shorts</ToggleGroup.Item>
						</ToggleGroup.Root>
					</div>
					<div class="space-y-2">
						<Label>Quality for new uploads</Label>
						<SimpleSelect
							class="w-full"
							label="Quality for new uploads"
							options={qualityOptions}
							value={c.watch_quality ?? 'default'}
							onchange={(v) => update.mutate({ watch_quality: v === 'default' ? null : v })}
						/>
					</div>
					<div class="space-y-1 text-sm">
						<p class="text-muted-foreground">
							{c.last_checked_at ? `Last checked ${ago(c.last_checked_at)}` : 'Not checked yet'}
						</p>
						{#if c.last_check_error}
							<p class="flex gap-1.5 text-brand-red">
								<TriangleAlertIcon class="mt-0.5 size-4 shrink-0" />
								<span class="break-words">{c.last_check_error}</span>
							</p>
						{/if}
					</div>
					<Button
						variant="outline"
						class="w-full"
						onclick={() => check.mutate()}
						disabled={check.isPending}
					>
						<RefreshIcon class={check.isPending ? 'animate-spin' : ''} /> Check now
					</Button>
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Creator</Card.Title>
					<Card.Description>Link this channel with the creator’s other channels.</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-2">
					<SimpleSelect
						class="w-full"
						label="Creator"
						options={creatorOptions}
						value={c.creator_pk ? String(c.creator_pk) : 'none'}
						onchange={setCreator}
					/>
					{#if c.creator_pk}
						<Button variant="link" class="px-0" href="/creators/{c.creator_pk}"
							>View creator page</Button
						>
					{/if}
				</Card.Content>
			</Card.Root>
		</aside>
	</div>

	<ConfirmDialog
		bind:open={confirmWatch}
		title="Turn on auto-archive?"
		description="New uploads will be downloaded automatically from now on."
		confirmLabel="Turn on"
		onconfirm={() => update.mutate({ watch_enabled: true, backfill })}
	>
		<div class="flex items-center gap-2">
			<Checkbox id="watch-backfill" bind:checked={backfill} />
			<Label for="watch-backfill" class="font-normal"
				>Also download videos already on the channel</Label
			>
		</div>
	</ConfirmDialog>

	<CreatorDialog bind:open={newCreator} channelIds={[c.id]} />
{/if}
