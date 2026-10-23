<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { api, call, errorMessage, mediaUrl, type CollectionDetail } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { duration } from '#lib/format.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import ConfirmDialog from '#lib/components/app/confirm-dialog.svelte';
	import PlayIcon from '@lucide/svelte/icons/play';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import TrashIcon from '@lucide/svelte/icons/trash-2';
	import ArrowUpIcon from '@lucide/svelte/icons/arrow-up';
	import ArrowDownIcon from '@lucide/svelte/icons/arrow-down';
	import XIcon from '@lucide/svelte/icons/x';
	import ListVideoIcon from '@lucide/svelte/icons/list-video';
	import CheckIcon from '@lucide/svelte/icons/check';

	const id = $derived(Number(page.params.id));
	const queryClient = useQueryClient();
	const collection = createQuery(() => queries.collection(id));
	const col = $derived(collection.data?.id === id ? collection.data : undefined);
	const total = $derived(col?.videos.reduce((sum, v) => sum + (v.duration_seconds ?? 0), 0) ?? 0);

	const refresh = () => {
		queryClient.invalidateQueries({ queryKey: keys.collection(id) });
		queryClient.invalidateQueries({ queryKey: keys.collections });
	};

	// Reorder optimistically; the server confirms (or the refetch puts it back).
	const reorder = createMutation(() => ({
		mutationFn: (ids: number[]) =>
			call(
				api.PUT('/api/collections/{collection_pk}/items', {
					params: { path: { collection_pk: id } },
					body: { video_ids: ids }
				})
			),
		onMutate: (ids) => {
			queryClient.setQueryData<CollectionDetail>(keys.collection(id), (old) =>
				old ? { ...old, videos: ids.map((v) => old.videos.find((x) => x.id === v)!) } : old
			);
		},
		onError: (e) => toast.error(e.message),
		onSettled: refresh
	}));

	function move(index: number, by: number) {
		if (!col) return;
		const ids = col.videos.map((v) => v.id);
		const [item] = ids.splice(index, 1);
		ids.splice(Math.max(0, Math.min(ids.length, index + by)), 0, item);
		reorder.mutate(ids);
	}

	const removeItem = createMutation(() => ({
		mutationFn: (videoPk: number) =>
			call(
				api.DELETE('/api/collections/{collection_pk}/items/{video_pk}', {
					params: { path: { collection_pk: id, video_pk: videoPk } }
				})
			),
		onSuccess: () => {
			refresh();
			queryClient.invalidateQueries({ queryKey: keys.videos });
		},
		onError: (e) => toast.error(e.message)
	}));

	let editing = $state(false);
	let name = $state('');
	let description = $state('');
	function startEdit() {
		name = col?.name ?? '';
		description = col?.description ?? '';
		editing = true;
	}
	const save = createMutation(() => ({
		mutationFn: () =>
			call(
				api.PATCH('/api/collections/{collection_pk}', {
					params: { path: { collection_pk: id } },
					body: { name: name.trim(), description: description.trim() || null }
				})
			),
		onSuccess: () => {
			refresh();
			editing = false;
		},
		onError: (e) => toast.error(e.message)
	}));

	let confirmDelete = $state(false);
	const remove = createMutation(() => ({
		mutationFn: () =>
			call(
				api.DELETE('/api/collections/{collection_pk}', { params: { path: { collection_pk: id } } })
			),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: keys.collections });
			queryClient.invalidateQueries({ queryKey: keys.videos });
			toast.success('Collection deleted');
			goto('/collections');
		},
		onError: (e) => toast.error(e.message)
	}));

	const firstUnwatched = $derived(col?.videos.find((v) => !v.watched) ?? col?.videos[0]);
</script>

{#if collection.isError}
	<PageHeader title="Collection" />
	<EmptyState
		icon={ListVideoIcon}
		title="Couldn't load this collection"
		description={errorMessage(collection.error)}
	>
		<Button variant="outline" href="/collections">All collections</Button>
	</EmptyState>
{:else if !col}
	<Skeleton class="mb-6 h-16 w-1/2" />
	<Skeleton class="h-64 w-full rounded-xl" />
{:else}
	<PageHeader
		title={col.name}
		description={[
			col.description,
			`${col.videos.length} ${col.videos.length === 1 ? 'video' : 'videos'}${total ? ` · ${duration(total)}` : ''}`
		]
			.filter(Boolean)
			.join(' — ')}
	>
		{#snippet actions()}
			{#if firstUnwatched}
				<Button href="/watch/{firstUnwatched.id}?collection={col.id}">
					<PlayIcon />
					{firstUnwatched === col.videos[0] ? 'Play all' : 'Continue'}
				</Button>
			{/if}
			<Button variant="outline" onclick={startEdit}><PencilIcon /> Edit</Button>
			<Button
				variant="ghost"
				size="icon"
				aria-label="Delete collection"
				onclick={() => (confirmDelete = true)}
			>
				<TrashIcon />
			</Button>
		{/snippet}
	</PageHeader>

	{#if !col.videos.length}
		<EmptyState
			icon={ListVideoIcon}
			title="This collection is empty"
			description="Use “Add to collection” from any video’s menu to add it here."
		>
			<Button variant="outline" href="/library">Browse the library</Button>
		</EmptyState>
	{:else}
		<ol class="divide-y overflow-hidden rounded-xl border bg-card">
			{#each col.videos as video, i (video.id)}
				<li class="group flex items-center gap-3 p-2 sm:p-3">
					<span
						class="hidden w-6 shrink-0 text-center text-sm text-muted-foreground tabular-nums sm:block"
					>
						{i + 1}
					</span>
					<a
						href="/watch/{video.id}?collection={col.id}"
						class="relative aspect-video w-28 shrink-0 overflow-hidden rounded-lg bg-muted sm:w-40"
					>
						{#if video.has_thumbnail}
							<img
								src={mediaUrl.thumbnail(video.id)}
								alt=""
								loading="lazy"
								class="size-full object-cover"
							/>
						{/if}
						{#if video.duration_seconds}
							<span
								class="absolute right-1 bottom-1 rounded bg-black/80 px-1 text-[0.65rem] font-medium text-white tabular-nums"
							>
								{duration(video.duration_seconds)}
							</span>
						{/if}
					</a>
					<div class="min-w-0 flex-1">
						<a
							href="/watch/{video.id}?collection={col.id}"
							class="line-clamp-2 text-sm font-medium hover:text-primary">{video.title}</a
						>
						<p class="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
							{#if video.watched}<CheckIcon class="size-3 text-success" />{/if}
							{video.channel?.name ?? video.channel?.handle ?? ''}
						</p>
					</div>
					<div class="flex shrink-0 flex-col gap-0.5 sm:flex-row">
						<Button
							variant="ghost"
							size="icon-sm"
							aria-label="Move up"
							disabled={i === 0 || reorder.isPending}
							onclick={() => move(i, -1)}
						>
							<ArrowUpIcon />
						</Button>
						<Button
							variant="ghost"
							size="icon-sm"
							aria-label="Move down"
							disabled={i === col.videos.length - 1 || reorder.isPending}
							onclick={() => move(i, 1)}
						>
							<ArrowDownIcon />
						</Button>
						<Button
							variant="ghost"
							size="icon-sm"
							aria-label="Remove from collection"
							disabled={removeItem.isPending}
							onclick={() => removeItem.mutate(video.id)}
						>
							<XIcon />
						</Button>
					</div>
				</li>
			{/each}
		</ol>
	{/if}

	<Dialog.Root bind:open={editing}>
		<Dialog.Content class="sm:max-w-md">
			<Dialog.Header>
				<Dialog.Title>Edit collection</Dialog.Title>
			</Dialog.Header>
			<form
				class="space-y-4"
				onsubmit={(e) => {
					e.preventDefault();
					if (name.trim()) save.mutate();
				}}
			>
				<div class="space-y-2">
					<Label for="edit-name">Name</Label>
					<Input id="edit-name" bind:value={name} maxlength={200} required />
				</div>
				<div class="space-y-2">
					<Label for="edit-description">Description</Label>
					<Textarea id="edit-description" bind:value={description} rows={3} />
				</div>
				<Dialog.Footer>
					<Button type="submit" disabled={!name.trim() || save.isPending}>Save</Button>
				</Dialog.Footer>
			</form>
		</Dialog.Content>
	</Dialog.Root>

	<ConfirmDialog
		bind:open={confirmDelete}
		title="Delete “{col.name}”?"
		description="Only the list is deleted; the videos stay in your archive."
		confirmLabel="Delete"
		destructive
		onconfirm={() => remove.mutate()}
	/>
{/if}
