<script lang="ts">
	import type { Video } from '#lib/api/client.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import VideoCard from './video-card.svelte';

	let {
		videos,
		loading = false,
		showChannel = true,
		skeletons = 12
	}: { videos: Video[]; loading?: boolean; showChannel?: boolean; skeletons?: number } = $props();
</script>

<div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,16rem),1fr))] gap-x-4 gap-y-7">
	{#each videos as video (video.id)}
		<VideoCard {video} {showChannel} />
	{/each}
	{#if loading}
		{#each { length: skeletons }, i (i)}
			<div class="space-y-2.5">
				<Skeleton class="aspect-video w-full rounded-xl" />
				<Skeleton class="h-4 w-11/12" />
				<Skeleton class="h-3 w-1/2" />
			</div>
		{/each}
	{/if}
</div>
