<!--
	The only place that knows about the player library (Video.js 10, packaged video skin).
	Pages deal in plain props and callbacks, so swapping the library touches this file only.
-->
<script lang="ts" module>
	export type Track = { lang: string; label: string; src: string };
</script>

<script lang="ts">
	import '@videojs/html/video/player';
	import '@videojs/html/video/skin';
	import { onMount, untrack } from 'svelte';

	let {
		src,
		poster,
		tracks = [],
		startAt = 0,
		autoplay = false,
		ontime,
		onpause,
		onended
	}: {
		src: string;
		poster?: string;
		tracks?: Track[];
		/** Seconds to resume from, applied once the media is ready. */
		startAt?: number;
		autoplay?: boolean;
		/** Called as playback advances (a few times a second). */
		ontime?: (position: number, duration: number) => void;
		onpause?: (position: number) => void;
		onended?: () => void;
	} = $props();

	let video = $state<HTMLVideoElement>();

	// Captured once per mount; the parent remounts the player (via {#key}) for a new video.
	const initialStart = untrack(() => startAt);
	const initialAutoplay = untrack(() => autoplay);

	function ready() {
		if (!video) return;
		if (initialStart > 0 && initialStart < video.duration - 1) video.currentTime = initialStart;
		if (initialAutoplay) video.play().catch(() => {}); // blocked autoplay just stays paused
	}

	/** Seek and play, used for timestamp links in the description. */
	export function seek(seconds: number) {
		if (!video) return;
		video.currentTime = seconds;
		video.play().catch(() => {});
		video.closest('video-player')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
	}

	export function position() {
		return video?.currentTime ?? 0;
	}

	onMount(() => () => video?.pause());
</script>

<video-player {poster}>
	<video-skin class="player-skin">
		<!-- svelte-ignore a11y_media_has_caption (archived subtitles are added below when present) -->
		<video
			bind:this={video}
			{src}
			playsinline
			preload="metadata"
			onloadedmetadata={ready}
			ontimeupdate={() => video && ontime?.(video.currentTime, video.duration)}
			onpause={() => video && !video.ended && onpause?.(video.currentTime)}
			onended={() => onended?.()}
		>
			{#each tracks as track (track.lang)}
				<track kind="subtitles" src={track.src} srclang={track.lang} label={track.label} />
			{/each}
		</video>
	</video-skin>
</video-player>

<style>
	.player-skin {
		display: block;
		width: 100%;
		aspect-ratio: 16 / 9;
		background: black;
		--media-accent-color: var(--primary);
		--media-accent-text-color: var(--primary-foreground);
		--media-border-radius: var(--radius-xl);
		--media-object-fit: contain;
	}
	/* Edge to edge on phones (the page removes its side padding there). */
	@media (width < 40rem) {
		.player-skin {
			--media-border-radius: 0;
		}
	}
</style>
