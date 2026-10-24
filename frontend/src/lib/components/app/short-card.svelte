<!-- A short in a row: a tall thumbnail that opens the scrolling shorts feed at that short. -->
<script lang="ts">
	import type { Video } from '#lib/api/client.js';
	import { mediaUrl } from '#lib/api/client.js';
	import { duration } from '#lib/format.js';
	import FilmIcon from '@lucide/svelte/icons/film';

	let { video }: { video: Video } = $props();
</script>

<article class="group flex flex-col gap-2">
	<a
		href="/shorts?start={video.id}"
		class="relative block aspect-[9/16] w-full overflow-hidden rounded-xl bg-muted ring-offset-background outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
		aria-label={video.title}
	>
		{#if video.has_thumbnail}
			<img
				src={mediaUrl.thumbnail(video.id)}
				alt=""
				loading="lazy"
				decoding="async"
				class={[
					'size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]',
					video.watched && 'opacity-60'
				]}
			/>
		{:else}
			<div class="grid size-full place-items-center text-muted-foreground"><FilmIcon /></div>
		{/if}
		{#if video.duration_seconds}
			<span
				class="absolute right-1.5 bottom-1.5 rounded-md bg-black/80 px-1.5 py-0.5 text-[0.7rem] font-medium text-white tabular-nums"
			>
				{duration(video.duration_seconds)}
			</span>
		{/if}
	</a>
	<h3 class="line-clamp-2 text-sm leading-snug font-medium">
		<a href="/shorts?start={video.id}" class="hover:text-primary">{video.title}</a>
	</h3>
</article>
