<script lang="ts">
	import type { Video } from '#lib/api/client.js';
	import { mediaUrl } from '#lib/api/client.js';
	import { ago, calendarDate, duration } from '#lib/format.js';
	import VideoMenu from './video-menu.svelte';
	import CheckIcon from '@lucide/svelte/icons/check';
	import FilmIcon from '@lucide/svelte/icons/film';

	let {
		video,
		showChannel = true,
		href = `/watch/${video.id}`,
		compact = false
	}: { video: Video; showChannel?: boolean; href?: string; compact?: boolean } = $props();

	const percent = $derived(
		video.watched
			? 100
			: video.duration_seconds && video.position_seconds
				? Math.min(100, (video.position_seconds / video.duration_seconds) * 100)
				: 0
	);
</script>

<article class={['group relative', compact ? 'flex gap-3' : 'flex flex-col gap-2.5']}>
	<a
		{href}
		class={[
			'relative block shrink-0 overflow-hidden rounded-xl bg-muted ring-offset-background outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
			compact ? 'aspect-video w-40' : 'aspect-video w-full'
		]}
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
		{#if video.watched}
			<span
				class="absolute top-1.5 left-1.5 flex items-center gap-1 rounded-md bg-black/75 px-1.5 py-0.5 text-[0.7rem] font-medium text-white"
			>
				<CheckIcon class="size-3" /> Watched
			</span>
		{/if}
		{#if video.content_kind !== 'video'}
			<span
				class="absolute top-1.5 right-1.5 rounded-md bg-black/75 px-1.5 py-0.5 text-[0.7rem] font-medium text-white capitalize"
			>
				{video.content_kind}
			</span>
		{/if}
		{#if percent > 0}
			<div class="absolute inset-x-0 bottom-0 h-1 bg-white/25">
				<div class="h-full bg-brand-red" style:width="{percent}%"></div>
			</div>
		{/if}
	</a>

	<div class="flex min-w-0 flex-1 gap-2">
		<div class="min-w-0 flex-1">
			<h3 class={['line-clamp-2 leading-snug font-medium', compact ? 'text-sm' : 'text-[0.95rem]']}>
				<a {href} class="hover:text-primary">{video.title}</a>
			</h3>
			<div class="mt-1 text-xs text-muted-foreground">
				{#if showChannel && video.channel}
					<a href="/channels/{video.channel.id}" class="block truncate hover:text-foreground">
						{video.channel.name ?? video.channel.handle}
					</a>
				{/if}
				<span title="Archived {ago(video.archived_at)}">
					{video.upload_date
						? calendarDate(video.upload_date)
						: `Archived ${ago(video.archived_at)}`}
				</span>
			</div>
		</div>
		<VideoMenu
			{video}
			class="-mr-2 shrink-0 opacity-100 transition-opacity data-[state=open]:opacity-100 md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100"
		/>
	</div>
</article>
