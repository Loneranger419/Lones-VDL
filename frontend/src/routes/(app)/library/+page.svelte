<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
	import * as ToggleGroup from '#lib/components/ui/toggle-group/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { errorMessage } from '#lib/api/client.js';
	import { queries, type VideoQuery } from '#lib/api/queries.js';
	import { onVisible } from '#lib/attachments.js';
	import { ui } from '#lib/ui-state.svelte.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import VideoGrid from '#lib/components/app/video-grid.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import SimpleSelect from '#lib/components/app/simple-select.svelte';
	import TagInput from '#lib/components/app/tag-input.svelte';
	import HiddenNotice from '#lib/components/app/hidden-notice.svelte';
	import LibraryIcon from '@lucide/svelte/icons/library-big';
	import SearchXIcon from '@lucide/svelte/icons/search-x';
	import XIcon from '@lucide/svelte/icons/x';

	const SORTS = [
		{ value: 'uploaded_desc', label: 'Recently uploaded' },
		{ value: 'archived_desc', label: 'Recently archived' },
		{ value: 'uploaded_asc', label: 'Oldest uploads' },
		{ value: 'watched_desc', label: 'Recently watched' },
		{ value: 'title', label: 'Title A–Z' },
		{ value: 'duration_desc', label: 'Longest' },
		{ value: 'duration_asc', label: 'Shortest' }
	];
	const WATCH = [
		{ value: 'any', label: 'Any progress' },
		{ value: 'unwatched', label: 'Unwatched' },
		{ value: 'in_progress', label: 'In progress' },
		{ value: 'watched', label: 'Watched' }
	];

	const INTEGRITY: Record<string, string> = {
		missing: 'files missing',
		mismatch: 'files changed since download',
		unverified: 'not checked yet',
		ok: 'verified'
	};

	// Filters live in the URL so the back button, bookmarks, and reloads keep them.
	const params = $derived(page.url.searchParams);
	const filters = $derived({
		q: params.get('q') || undefined,
		// Absent: everything but shorts. 'all': everything.
		kind: params.get('kind') || undefined,
		watch: (params.get('watch') || undefined) as VideoQuery['watch'],
		channel: params.get('channel') ? Number(params.get('channel')) : undefined,
		integrity: (params.get('integrity') || undefined) as VideoQuery['integrity'],
		tag: params.getAll('tag'),
		// No preset in the URL means the default one; 'none' turns tag filtering off.
		preset: params.get('preset') || 'default',
		sort: (params.get('sort') || 'uploaded_desc') as VideoQuery['sort']
	});
	const filtered = $derived(
		Boolean(
			filters.q ||
			filters.kind ||
			filters.watch ||
			filters.channel ||
			filters.integrity ||
			filters.tag.length
		)
	);

	function setTags(tags: string[]) {
		const next = new URLSearchParams(page.url.search);
		next.delete('tag');
		for (const tag of tags) next.append('tag', tag);
		goto(`/library${next.size ? `?${next}` : ''}`, { replace: true, reset: false });
	}

	function setParam(key: string, value: string | undefined, fallback = '') {
		const next = new URLSearchParams(page.url.search);
		if (value && value !== fallback) next.set(key, value);
		else next.delete(key);
		goto(`/library${next.size ? `?${next}` : ''}`, { replace: true, reset: false });
	}

	const videoQuery = $derived({
		...filters,
		// Shorts never carry the tag filter.
		preset: filters.kind === 'short' ? 'none' : filters.preset,
		kind: filters.kind && filters.kind !== 'all' ? (filters.kind as VideoQuery['kind']) : undefined,
		// A search looks through shorts too; browsing leaves them out unless a kind is chosen.
		exclude_kind: filters.kind || filters.q ? undefined : ['short' as const]
	});
	const videos = createInfiniteQuery(() => queries.videoPages(videoQuery));
	const channels = createQuery(() => queries.channels());
	const presets = createQuery(() => queries.presets());

	const items = $derived(videos.data?.pages.flatMap((p) => p.items) ?? []);
	const total = $derived(videos.data?.pages[0]?.total);
	const hidden = $derived(videos.data?.pages[0]?.hidden ?? 0);
	const activePreset = $derived.by(() => {
		const book = presets.data;
		if (!book || filters.preset === 'none') return undefined;
		const id = filters.preset === 'default' ? book.default_id : Number(filters.preset);
		return book.presets.find((p) => p.id === id);
	});
	const presetOptions = $derived.by(() => {
		const book = presets.data;
		const standing = book?.presets.find((p) => p.id === book.default_id);
		return [
			{ value: 'default', label: standing ? `Default: ${standing.name}` : 'Default: no filter' },
			...(book?.presets ?? [])
				.filter((p) => p.id !== book?.default_id)
				.map((p) => ({ value: String(p.id), label: p.name })),
			{ value: 'none', label: 'No tag filter' }
		];
	});

	const channelOptions = $derived([
		{ value: '', label: 'All channels' },
		...(channels.data ?? [])
			.map((c) => ({ value: String(c.id), label: c.name ?? c.handle ?? c.channel_id }))
			.sort((a, b) => a.label.localeCompare(b.label))
	]);

	function more() {
		if (videos.hasNextPage && !videos.isFetchingNextPage) videos.fetchNextPage();
	}
</script>

<PageHeader
	title="Library"
	description={total === undefined
		? undefined
		: `${total.toLocaleString()} ${total === 1 ? 'video' : 'videos'}${filtered ? ' match' : ''}`}
/>

<div class="mb-6 flex flex-wrap items-center gap-2">
	<ToggleGroup.Root
		type="single"
		variant="outline"
		size="sm"
		value={filters.kind ?? 'default'}
		onValueChange={(v) => setParam('kind', v, 'default')}
	>
		<ToggleGroup.Item value="default">No shorts</ToggleGroup.Item>
		<ToggleGroup.Item value="all">All</ToggleGroup.Item>
		<ToggleGroup.Item value="video">Videos</ToggleGroup.Item>
		<ToggleGroup.Item value="stream">Streams</ToggleGroup.Item>
		<ToggleGroup.Item value="short">Shorts</ToggleGroup.Item>
	</ToggleGroup.Root>
	<!-- Phone: the selects share rows evenly; wider screens: one toolbar line. -->
	<div class="flex w-full flex-wrap gap-2 sm:contents">
		<SimpleSelect
			size="sm"
			class="min-w-36 flex-1 sm:w-40 sm:flex-none"
			label="Watch progress"
			options={WATCH}
			value={filters.watch ?? 'any'}
			onchange={(v) => setParam('watch', v, 'any')}
		/>
		<SimpleSelect
			size="sm"
			class="min-w-36 flex-1 sm:w-48 sm:flex-none"
			label="Channel"
			options={channelOptions}
			value={filters.channel ? String(filters.channel) : ''}
			onchange={(v) => setParam('channel', v)}
		/>
		<SimpleSelect
			size="sm"
			class="min-w-36 flex-1 sm:w-48 sm:flex-none"
			label="Tag filter preset"
			options={presetOptions}
			value={filters.preset}
			onchange={(v) => setParam('preset', v, 'default')}
		/>
		<SimpleSelect
			size="sm"
			class="min-w-36 flex-1 sm:ml-auto sm:w-44 sm:flex-none"
			label="Sort"
			options={SORTS}
			value={filters.sort}
			onchange={(v) => setParam('sort', v, 'uploaded_desc')}
		/>
	</div>
	<TagInput
		class="w-full"
		label="Only videos with these tags"
		placeholder="Filter by tag"
		tags={filters.tag}
		onchange={setTags}
	/>
	<div class="w-full empty:hidden">
		<HiddenNotice
			{hidden}
			preset={activePreset?.name ?? ''}
			onshow={() => setParam('preset', 'none', 'default')}
		/>
	</div>
	{#if filters.integrity}
		<div class="flex w-full items-center gap-2 text-sm">
			<span class="text-muted-foreground">Integrity:</span>
			<span class="font-medium">{INTEGRITY[filters.integrity] ?? filters.integrity}</span>
			<Button
				variant="ghost"
				size="icon-sm"
				aria-label="Clear integrity filter"
				onclick={() => setParam('integrity', undefined)}
			>
				<XIcon />
			</Button>
		</div>
	{/if}
	{#if filters.q}
		<div class="flex w-full items-center gap-2 text-sm">
			<span class="text-muted-foreground">Results for</span>
			<span class="font-medium">“{filters.q}”</span>
			<Button
				variant="ghost"
				size="icon-sm"
				aria-label="Clear search"
				onclick={() => setParam('q', undefined)}
			>
				<XIcon />
			</Button>
		</div>
	{/if}
</div>

{#if videos.isError}
	<EmptyState title="Couldn't load the library" description={errorMessage(videos.error)}>
		<Button variant="outline" onclick={() => videos.refetch()}>Try again</Button>
	</EmptyState>
{:else if !videos.isPending && !items.length}
	{#if filtered}
		<EmptyState
			icon={SearchXIcon}
			title="No matches"
			description="Try a different search or clear some filters."
		>
			<Button variant="outline" onclick={() => goto('/library', { replace: true })}
				>Clear filters</Button
			>
		</EmptyState>
	{:else}
		<EmptyState
			icon={LibraryIcon}
			title="Your archive is empty"
			description="Downloaded videos show up here. Start with a video, a playlist, or a whole channel."
		>
			<Button onclick={() => ui.openAdd()}>Add a download</Button>
		</EmptyState>
	{/if}
{:else}
	<VideoGrid videos={items} loading={videos.isPending || videos.isFetchingNextPage} />
	{#if videos.hasNextPage && !videos.isFetchingNextPage}
		<!-- Remounts after each page, so it fires again if it is still on screen. -->
		<div {@attach onVisible(more)} class="h-px"></div>
	{/if}
{/if}
