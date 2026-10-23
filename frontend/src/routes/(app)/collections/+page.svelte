<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { mediaUrl } from '#lib/api/client.js';
	import { queries } from '#lib/api/queries.js';
	import { ago } from '#lib/format.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import NewCollectionDialog from '#lib/components/app/new-collection-dialog.svelte';
	import ListVideoIcon from '@lucide/svelte/icons/list-video';
	import PlusIcon from '@lucide/svelte/icons/plus';

	const collections = createQuery(() => queries.collections());
	let creating = $state(false);
</script>

<PageHeader title="Collections" description="Your own playlists, in the order you choose.">
	{#snippet actions()}
		<Button onclick={() => (creating = true)}><PlusIcon /> New collection</Button>
	{/snippet}
</PageHeader>

{#if collections.isPending}
	<div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,16rem),1fr))] gap-x-4 gap-y-6">
		{#each { length: 4 }, i (i)}<Skeleton class="aspect-video rounded-xl" />{/each}
	</div>
{:else if !collections.data?.length}
	<EmptyState
		icon={ListVideoIcon}
		title="No collections yet"
		description="Create one here, or use “Add to collection” from any video’s menu."
	>
		<Button onclick={() => (creating = true)}>New collection</Button>
	</EmptyState>
{:else}
	<div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,16rem),1fr))] gap-x-4 gap-y-6">
		{#each collections.data as collection (collection.id)}
			<a href="/collections/{collection.id}" class="group space-y-2.5">
				<div class="relative aspect-video overflow-hidden rounded-xl bg-muted">
					<!-- Stacked look: a sliver of "cards" behind the cover. -->
					<div class="absolute inset-x-3 top-0 h-2 rounded-b-md bg-primary/25"></div>
					{#if collection.cover_video_pk}
						<img
							src={mediaUrl.thumbnail(collection.cover_video_pk)}
							alt=""
							loading="lazy"
							class="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
						/>
					{:else}
						<div class="grid size-full place-items-center text-muted-foreground">
							<ListVideoIcon class="size-8" />
						</div>
					{/if}
					<span
						class="absolute right-1.5 bottom-1.5 flex items-center gap-1 rounded-md bg-black/80 px-1.5 py-0.5 text-[0.7rem] font-medium text-white"
					>
						<ListVideoIcon class="size-3" />
						{collection.item_count}
					</span>
				</div>
				<div>
					<h3 class="truncate font-medium group-hover:text-primary">{collection.name}</h3>
					<p class="text-xs text-muted-foreground">Updated {ago(collection.updated_at)}</p>
				</div>
			</a>
		{/each}
	</div>
{/if}

<NewCollectionDialog bind:open={creating} navigate />
