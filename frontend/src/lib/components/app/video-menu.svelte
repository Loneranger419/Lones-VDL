<script lang="ts">
	import { goto } from '$app/navigation';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { api, call, type Video } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import ConfirmDialog from './confirm-dialog.svelte';
	import NewCollectionDialog from './new-collection-dialog.svelte';
	import EllipsisIcon from '@lucide/svelte/icons/ellipsis-vertical';
	import EyeIcon from '@lucide/svelte/icons/eye';
	import EyeOffIcon from '@lucide/svelte/icons/eye-off';
	import ListPlusIcon from '@lucide/svelte/icons/list-plus';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import TrashIcon from '@lucide/svelte/icons/trash-2';
	import TvIcon from '@lucide/svelte/icons/tv';

	let {
		video,
		class: className = '',
		ondeleted
	}: { video: Video; class?: string; ondeleted?: () => void } = $props();

	const queryClient = useQueryClient();
	let menuOpen = $state(false);
	let confirmDelete = $state(false);
	let deleteFiles = $state(true);
	let newCollection = $state(false);

	// Collections are only fetched once the menu is opened.
	const collections = createQuery(() => ({ ...queries.collections(), enabled: menuOpen }));

	const refresh = () => {
		queryClient.invalidateQueries({ queryKey: keys.videos });
		queryClient.invalidateQueries({ queryKey: keys.collections });
	};

	const setWatched = createMutation(() => ({
		mutationFn: (watched: boolean) =>
			call(
				api.PUT('/api/videos/{video_pk}/watched', {
					params: { path: { video_pk: video.id } },
					body: { watched }
				})
			),
		onSuccess: refresh,
		onError: (e) => toast.error(e.message)
	}));

	const addTo = createMutation(() => ({
		mutationFn: (collection: { id: number; name: string }) =>
			call(
				api.POST('/api/collections/{collection_pk}/items', {
					params: { path: { collection_pk: collection.id } },
					body: { video_ids: [video.id] }
				})
			).then(() => collection),
		onSuccess: (collection) => {
			refresh();
			toast.success(`Added to ${collection.name}`);
		},
		onError: (e) => toast.error(e.message)
	}));

	const remove = createMutation(() => ({
		mutationFn: () =>
			call(
				api.DELETE('/api/videos/{video_pk}', {
					params: { path: { video_pk: video.id }, query: { delete_files: deleteFiles } }
				})
			),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: keys.videos });
			queryClient.invalidateQueries({ queryKey: keys.channels });
			queryClient.invalidateQueries({ queryKey: keys.stats });
			toast.success('Video deleted');
			ondeleted?.();
		},
		onError: (e) => toast.error(e.message)
	}));
</script>

<DropdownMenu.Root bind:open={menuOpen}>
	<DropdownMenu.Trigger class={className}>
		{#snippet child({ props })}
			<Button {...props} variant="ghost" size="icon-sm" aria-label="Video actions">
				<EllipsisIcon />
			</Button>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end" class="w-56">
		<DropdownMenu.Item onclick={() => setWatched.mutate(!video.watched)}>
			{#if video.watched}<EyeOffIcon /> Mark as unwatched{:else}<EyeIcon /> Mark as watched{/if}
		</DropdownMenu.Item>
		<DropdownMenu.Sub>
			<DropdownMenu.SubTrigger><ListPlusIcon /> Add to collection</DropdownMenu.SubTrigger>
			<DropdownMenu.SubContent class="max-h-72 w-52 overflow-y-auto">
				{#each collections.data ?? [] as collection (collection.id)}
					<DropdownMenu.Item onclick={() => addTo.mutate(collection)}>
						<span class="truncate">{collection.name}</span>
					</DropdownMenu.Item>
				{:else}
					{#if collections.isSuccess}
						<DropdownMenu.Item disabled>No collections yet</DropdownMenu.Item>
					{/if}
				{/each}
				<DropdownMenu.Separator />
				<DropdownMenu.Item onclick={() => (newCollection = true)}>
					<PlusIcon /> New collection…
				</DropdownMenu.Item>
			</DropdownMenu.SubContent>
		</DropdownMenu.Sub>
		{#if video.channel}
			<DropdownMenu.Item onclick={() => goto(`/channels/${video.channel?.id}`)}>
				<TvIcon /> Go to channel
			</DropdownMenu.Item>
		{/if}
		<DropdownMenu.Separator />
		<DropdownMenu.Item variant="destructive" onclick={() => (confirmDelete = true)}>
			<TrashIcon /> Delete…
		</DropdownMenu.Item>
	</DropdownMenu.Content>
</DropdownMenu.Root>

<ConfirmDialog
	bind:open={confirmDelete}
	title="Delete this video?"
	description="“{video.title}” will be removed from your library. Channel auto-archive will not download it again; you can still re-add it by URL."
	confirmLabel="Delete"
	destructive
	onconfirm={() => remove.mutate()}
>
	<div class="flex items-center gap-2">
		<Checkbox id="delete-files-{video.id}" bind:checked={deleteFiles} />
		<Label for="delete-files-{video.id}" class="font-normal">Also delete the files from disk</Label>
	</div>
</ConfirmDialog>

<NewCollectionDialog bind:open={newCollection} videoIds={[video.id]} />
