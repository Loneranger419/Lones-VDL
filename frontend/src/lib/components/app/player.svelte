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
		chapters,
		startAt = 0,
		autoplay = false,
		ontime,
		onpause,
		onended
	}: {
		src: string;
		poster?: string;
		tracks?: Track[];
		/** WebVTT chapters track; the skin draws the chapters on its timeline. */
		chapters?: string;
		/** Seconds to resume from, applied once the media is ready. */
		startAt?: number;
		autoplay?: boolean;
		/** Called as playback advances (a few times a second). */
		ontime?: (position: number, duration: number) => void;
		onpause?: (position: number) => void;
		onended?: () => void;
	} = $props();

	let video = $state<HTMLVideoElement>();

	// Volume, mute, speed, and captions on/off carry over between videos and visits. A new video is a new element
	// (the page remounts the player), so the saved values are applied to each one.
	const PREFS_KEY = 'lones-vdl:player';
	type Prefs = { volume?: number; muted?: boolean; rate?: number; captions?: boolean };

	function loadPrefs(): Prefs {
		try {
			return JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}') as Prefs;
		} catch {
			return {};
		}
	}

	function savePrefs(changes: Prefs) {
		try {
			localStorage.setItem(PREFS_KEY, JSON.stringify({ ...loadPrefs(), ...changes }));
		} catch {
			// Storage can be blocked (private window); the player still works.
		}
	}

	function applyPrefs() {
		if (!video) return;
		const { volume, muted, rate } = loadPrefs();
		if (typeof volume === 'number' && volume >= 0 && volume <= 1) video.volume = volume;
		if (typeof muted === 'boolean') video.muted = muted;
		if (typeof rate === 'number' && rate >= 0.25 && rate <= 4) {
			video.defaultPlaybackRate = rate; // survives the reset that loading a source causes
			video.playbackRate = rate;
		}
	}

	$effect(() => {
		if (video) untrack(applyPrefs);
	});

	// --- Captions: on/off is remembered; with none downloaded, say so for a few seconds. ---------
	const NOTICE_MS = 5000;
	let notice = $state(false);
	let noticeTimer: ReturnType<typeof setTimeout> | undefined;

	const captionTracks = () =>
		[...(video?.textTracks ?? [])].filter((t) => t.kind === 'subtitles' || t.kind === 'captions');

	function applyCaptions(announce: boolean) {
		if (!video || !loadPrefs().captions) return;
		const list = captionTracks();
		if (list.length) {
			if (!list.some((t) => t.mode === 'showing')) {
				(list.find((t) => t.language.startsWith('en')) ?? list[0]).mode = 'showing';
			}
		} else if (announce) {
			notice = true;
			clearTimeout(noticeTimer);
			noticeTimer = setTimeout(() => (notice = false), NOTICE_MS);
		}
	}

	function saveCaptions() {
		savePrefs({ captions: captionTracks().some((t) => t.mode === 'showing') });
	}

	// Subtitles fetched while the page is open arrive as new tracks.
	$effect(() => {
		void tracks.length;
		untrack(() => applyCaptions(false));
	});

	$effect(() => {
		const list = video?.textTracks;
		list?.addEventListener('change', saveCaptions);
		return () => list?.removeEventListener('change', saveCaptions);
	});

	// Captured once per mount; the parent remounts the player (via {#key}) for a new video.
	const initialStart = untrack(() => startAt);
	const initialAutoplay = untrack(() => autoplay);

	function ready() {
		if (!video) return;
		applyPrefs();
		applyCaptions(true);
		if (initialStart > 0 && initialStart < video.duration - 1) video.currentTime = initialStart;
		if (initialAutoplay) video.play().catch(() => {}); // blocked autoplay just stays paused
	}

	/** Move to a time without changing whether it plays (scrubbing). */
	export function jump(seconds: number) {
		if (video) video.currentTime = seconds;
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

	/** True while the video is actually playing (not paused, not finished). */
	export function playing() {
		return !!video && !video.paused && !video.ended;
	}

	onMount(() => () => {
		video?.pause();
		clearTimeout(noticeTimer);
	});
</script>

<div class="relative">
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
				onvolumechange={() => video && savePrefs({ volume: video.volume, muted: video.muted })}
				onratechange={() => video && savePrefs({ rate: video.playbackRate })}
			>
				{#if chapters}
					<track kind="chapters" src={chapters} srclang="en" label="Chapters" default />
				{/if}
				{#each tracks as track (track.lang)}
					<track kind="subtitles" src={track.src} srclang={track.lang} label={track.label} />
				{/each}
			</video>
		</video-skin>
	</video-player>
	{#if notice}
		<p
			role="status"
			class="pointer-events-none absolute inset-x-0 top-3 z-10 mx-auto w-fit max-w-[90%] rounded-lg bg-black/80 px-3 py-2 text-center text-sm text-white"
		>
			Captions are on, but none are downloaded for this video. Click “Get subtitles” below the
			video.
		</p>
	{/if}
</div>

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
