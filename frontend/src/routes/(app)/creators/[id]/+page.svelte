<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import {
		createInfiniteQuery,
		createMutation,
		createQuery,
		useQueryClient
	} from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { api, call, errorMessage } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { onVisible } from '#lib/attachments.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import VideoGrid from '#lib/components/app/video-grid.svelte';
	import ChannelAvatar from '#lib/components/app/channel-avatar.svelte';
	import ConfirmDialog from '#lib/components/app/confirm-dialog.svelte';
	import CreatorDialog from '#lib/components/app/creator-dialog.svelte';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import TrashIcon from '@lucide/svelte/icons/trash-2';
	import UsersIcon from '@lucide/svelte/icons/users';
	import FilmIcon from '@lucide/svelte/icons/film';

	const id = $derived(Number(page.params.id));
	const queryClient = useQueryClient();
	const creator = createQuery(() => queries.creator(id));
	const cr = $derived(creator.data?.id === id ? creator.data : undefined);

	const videos = createInfiniteQuery(() =>
		queries.videoPages({ creator: id, sort: 'uploaded_desc' })
	);
	const items = $derived(videos.data?.pages.flatMap((p) => p.items) ?? []);
	function more() {
		if (videos.hasNextPage && !videos.isFetchingNextPage) videos.fetchNextPage();
	}

	let editing = $state(false);
	let confirmDelete = $state(false);

	const remove = createMutation(() => ({
		mutationFn: () =>
			call(api.DELETE('/api/creators/{creator_pk}', { params: { path: { creator_pk: id } } })),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: keys.creators });
			queryClient.invalidateQueries({ queryKey: keys.channels });
			toast.success('Creator deleted');
			goto('/channels?tab=creators');
		},
		onError: (e) => toast.error(e.message)
	}));
</script>

{#if creator.isError}
	<PageHeader title="Creator" />
	<EmptyState
		icon={UsersIcon}
		title="Couldn't load this creator"
		description={errorMessage(creator.error)}
	>
		<Button variant="outline" href="/channels?tab=creators">All creators</Button>
	</EmptyState>
{:else if !cr}
	<Skeleton class="mb-6 h-16 w-1/2" />
{:else}
	<PageHeader title={cr.name} description={cr.notes ?? undefined}>
		{#snippet actions()}
			<Button variant="outline" onclick={() => (editing = true)}><PencilIcon /> Edit</Button>
			<Button
				variant="ghost"
				size="icon"
				aria-label="Delete creator"
				onclick={() => (confirmDelete = true)}
			>
				<TrashIcon />
			</Button>
		{/snippet}
	</PageHeader>

	{#if cr.channels.length}
		<div class="mb-8 flex flex-wrap gap-3">
			{#each cr.channels as channel (channel.id)}
				<a
					href="/channels/{channel.id}"
					class="flex items-center gap-3 rounded-full border bg-card py-1.5 pr-4 pl-1.5 transition-colors hover:border-primary/40"
				>
					<ChannelAvatar {channel} class="size-8" />
					<span class="text-sm font-medium">{channel.name ?? channel.handle}</span>
					<span class="text-xs text-muted-foreground capitalize">{channel.platform}</span>
				</a>
			{/each}
		</div>
	{/if}

	{#if !videos.isPending && !items.length}
		<EmptyState
			icon={FilmIcon}
			title="No videos yet"
			description={cr.channels.length
				? 'None of the linked channels have archived videos.'
				: 'Link channels to this creator to see their videos here.'}
		>
			{#if !cr.channels.length}<Button onclick={() => (editing = true)}>Link channels</Button>{/if}
		</EmptyState>
	{:else}
		<VideoGrid videos={items} loading={videos.isPending || videos.isFetchingNextPage} />
		{#if videos.hasNextPage && !videos.isFetchingNextPage}
			<div {@attach onVisible(more)} class="h-px"></div>
		{/if}
	{/if}

	<CreatorDialog bind:open={editing} creator={cr} />
	<ConfirmDialog
		bind:open={confirmDelete}
		title="Delete {cr.name}?"
		description="The channels and their videos stay in your archive; they are just no longer grouped."
		confirmLabel="Delete"
		destructive
		onconfirm={() => remove.mutate()}
	/>
{/if}
