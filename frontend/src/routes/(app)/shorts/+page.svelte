<!--
	Shorts as a scrolling feed, like YouTube and TikTok: one short fills the view, scroll (or
	use the arrow keys) for the next. Only the short in view is loaded and plays; it loops.
	`?start=<id>` opens the feed at that short, `?channel=<id>` limits it to one channel.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { createInfiniteQuery, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { api, mediaUrl, type Video } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronUpIcon from '@lucide/svelte/icons/chevron-up';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import PlayIcon from '@lucide/svelte/icons/play';
	import SmartphoneIcon from '@lucide/svelte/icons/smartphone';
	import Volume2Icon from '@lucide/svelte/icons/volume-2';
	import VolumeXIcon from '@lucide/svelte/icons/volume-x';

	const queryClient = useQueryClient();
	const PREFS_KEY = 'lones-vdl:player'; // volume and mute are shared with the Watch page player

	const start = Number(page.url.searchParams.get('start')) || 0; // read once: scrolling moves on
	const channel = $derived(
		page.url.searchParams.get('channel') ? Number(page.url.searchParams.get('channel')) : undefined
	);

	const feed = createInfiniteQuery(() =>
		queries.videoPages({ kind: 'short', sort: 'uploaded_desc', channel })
	);
	// The short that was clicked may be further down than the first page.
	const opened = createQuery(() => ({ ...queries.video(start), enabled: start > 0 }));

	const items = $derived.by((): Video[] => {
		const list = feed.data?.pages.flatMap((p) => p.items) ?? [];
		const first = opened.data;
		if (first && first.content_kind === 'short' && !list.some((v) => v.id === first.id)) {
			return [first as Video, ...list];
		}
		return list;
	});

	let scroller = $state<HTMLDivElement>();
	let frame = $state<HTMLDivElement>();
	let active = $state(0);
	let height = $state(0); // px of one short = the visible height of the scroller
	let playing = $state(false);
	let muted = $state(false);
	let volume = $state(loadPrefs().volume ?? 1); // 0..1, remembered between shorts and visits
	let progress = $state(0);
	let video = $state<HTMLVideoElement>();
	let positioned = false;

	function loadPrefs(): { volume?: number; muted?: boolean } {
		try {
			return JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}');
		} catch {
			return {};
		}
	}
	function savePrefs(changes: { volume?: number; muted?: boolean }) {
		try {
			localStorage.setItem(PREFS_KEY, JSON.stringify({ ...loadPrefs(), ...changes }));
		} catch {
			// Storage can be blocked; the feed still works.
		}
	}

	// The feed fills the space under the top bar; measured because the banner above can come and go.
	function measure() {
		if (!frame) return;
		const top = frame.getBoundingClientRect().top + window.scrollY;
		const bottom = window.matchMedia('(min-width: 768px)').matches
			? 24
			: parseFloat(getComputedStyle(frame).getPropertyValue('--feed-bottom')) || 76;
		height = Math.max(window.innerHeight - top - bottom, 320);
	}
	$effect(() => {
		measure();
		window.addEventListener('resize', measure);
		return () => window.removeEventListener('resize', measure);
	});

	// Open at the clicked short (it is first in the list, unless it was already in the first page).
	$effect(() => {
		if (positioned || !scroller || !height || !items.length) return;
		if (start && opened.isPending && !items.some((v) => v.id === start)) return;
		positioned = true;
		const index = Math.max(
			items.findIndex((v) => v.id === start),
			0
		);
		scroller.scrollTo({ top: index * height });
		active = index;
	});

	let raf = 0;
	function onscroll() {
		cancelAnimationFrame(raf);
		raf = requestAnimationFrame(() => {
			if (scroller && height) active = Math.round(scroller.scrollTop / height);
		});
	}

	// The browser's own smooth scroll and snap take about half a second; this is much quicker.
	const SCROLL_MS = 300;
	const WHEEL_COOLDOWN_MS = 400; // a trackpad flick sends events for a while after it
	let animating = 0;
	let lockedUntil = 0;

	function go(delta: number) {
		if (!scroller) return;
		const next = Math.min(Math.max(active + delta, 0), items.length - 1);
		const from = scroller.scrollTop;
		const to = next * height;
		cancelAnimationFrame(animating);
		scroller.style.scrollSnapType = 'none'; // snapping would fight the animation
		const began = performance.now();
		const step = (now: number) => {
			const t = Math.min((now - began) / SCROLL_MS, 1);
			scroller!.scrollTop = from + (to - from) * (1 - (1 - t) ** 3);
			if (t < 1) animating = requestAnimationFrame(step);
			else scroller!.style.scrollSnapType = '';
		};
		animating = requestAnimationFrame(step);
	}

	// Mouse wheel / trackpad: one flick moves one short, quickly (touch keeps the native snap).
	function wheel(element: HTMLElement) {
		const onwheel = (event: WheelEvent) => {
			event.preventDefault();
			const now = performance.now();
			if (now < lockedUntil || Math.abs(event.deltaY) < 4) return;
			lockedUntil = now + WHEEL_COOLDOWN_MS;
			go(event.deltaY > 0 ? 1 : -1);
		};
		element.addEventListener('wheel', onwheel, { passive: false });
		return () => element.removeEventListener('wheel', onwheel);
	}

	// Near the end of what is loaded: fetch more.
	$effect(() => {
		if (
			items.length &&
			active >= items.length - 3 &&
			feed.hasNextPage &&
			!feed.isFetchingNextPage
		) {
			feed.fetchNextPage();
		}
	});

	// --- the short in view ----------------------------------------------------------------------
	let seen = { id: 0, furthest: 0 };

	function flush() {
		if (!seen.id || seen.furthest <= 0) return;
		api
			.PUT('/api/videos/{video_pk}/progress', {
				params: { path: { video_pk: seen.id } },
				body: { position_seconds: seen.furthest },
				keepalive: true
			})
			.catch(() => {});
		seen = { id: seen.id, furthest: 0 };
	}

	// Moving to another short saves how far the last one was watched (the end marks it watched).
	$effect(() => {
		const current = items[active];
		untrackFlush(current?.id ?? 0);
	});
	function untrackFlush(id: number) {
		if (seen.id !== id) {
			flush();
			seen = { id, furthest: 0 };
			progress = 0;
		}
	}

	function attach(element: HTMLVideoElement) {
		video = element;
		const { volume: saved, muted: wasMuted } = loadPrefs();
		if (typeof saved === 'number' && saved >= 0 && saved <= 1) element.volume = saved;
		volume = element.volume;
		muted = element.muted = wasMuted ?? false;
		element.play().catch(() => (playing = false)); // blocked autoplay waits for a tap
		return () => {
			if (video === element) video = undefined;
		};
	}

	function toggle() {
		if (!video) return;
		if (video.paused) video.play().catch(() => {});
		else video.pause();
	}
	function setVolume(value: number) {
		volume = value;
		savePrefs({ volume: value });
		if (!video) return;
		video.volume = value;
		if (value > 0 && video.muted) video.muted = false; // moving the slider up un-mutes
	}
	function toggleMute() {
		if (!video) return;
		video.muted = !video.muted;
	}

	function onkeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (target?.closest('input, textarea, select, [contenteditable]')) return;
		if (event.metaKey || event.ctrlKey || event.altKey) return;
		const actions: Record<string, () => void> = {
			ArrowDown: () => go(1),
			j: () => go(1),
			ArrowUp: () => go(-1),
			k: () => go(-1),
			' ': toggle,
			m: toggleMute
		};
		const action = actions[event.key];
		if (action) {
			event.preventDefault();
			action();
		}
	}

	$effect(() => {
		window.addEventListener('pagehide', flush);
		return () => {
			window.removeEventListener('pagehide', flush);
			cancelAnimationFrame(raf);
			cancelAnimationFrame(animating);
			flush();
			// Lists and the Home page show progress; refresh them with what was just watched.
			queryClient.invalidateQueries({ queryKey: keys.videos });
		};
	});
</script>

<svelte:head><title>Shorts · Lones-VDL</title></svelte:head>
<svelte:window {onkeydown} />

{#if feed.isError}
	<EmptyState
		icon={SmartphoneIcon}
		title="Couldn't load shorts"
		description="Try again in a moment."
	>
		<Button variant="outline" onclick={() => feed.refetch()}>Retry</Button>
	</EmptyState>
{:else if !feed.isPending && !items.length}
	<EmptyState
		icon={SmartphoneIcon}
		title="No shorts yet"
		description="Shorts you download show up here as a scrolling feed."
	></EmptyState>
{:else}
	<div
		bind:this={frame}
		class="relative mx-auto w-full max-w-md [--feed-bottom:calc(var(--bottom-nav-height)+1rem)]"
		style:height="{height}px"
	>
		<div
			bind:this={scroller}
			{@attach wheel}
			{onscroll}
			class="size-full snap-y snap-mandatory [scrollbar-width:none] overflow-y-auto overscroll-contain rounded-xl bg-black"
			tabindex="-1"
		>
			{#each items as short, i (short.id)}
				<section class="relative snap-start snap-always bg-black" style:height="{height}px">
					{#if i === active}
						<!-- svelte-ignore a11y_media_has_caption (shorts have no captions fetched) -->
						<video
							{@attach attach}
							src={mediaUrl.video(short.id)}
							poster={short.has_thumbnail ? mediaUrl.thumbnail(short.id) : undefined}
							class="size-full object-contain"
							loop
							playsinline
							preload="auto"
							onclick={toggle}
							onplay={() => (playing = true)}
							onpause={() => (playing = false)}
							onvolumechange={(e) => {
								muted = e.currentTarget.muted;
								volume = e.currentTarget.volume;
								savePrefs({ volume: e.currentTarget.volume, muted: e.currentTarget.muted });
							}}
							ontimeupdate={(e) => {
								const { currentTime, duration } = e.currentTarget;
								progress = duration ? currentTime / duration : 0;
								if (seen.id === short.id) seen.furthest = Math.max(seen.furthest, currentTime);
							}}
						></video>
					{:else if short.has_thumbnail}
						<img src={mediaUrl.thumbnail(short.id)} alt="" class="size-full object-contain" />
					{/if}

					{#if i === active && !playing}
						<button
							type="button"
							class="absolute inset-0 grid place-items-center text-white"
							aria-label="Play"
							onclick={toggle}
						>
							<span class="rounded-full bg-black/50 p-4"><PlayIcon class="size-8" /></span>
						</button>
					{/if}

					<div
						class="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-4 pb-5 text-white"
					>
						{#if short.channel}
							<a
								href="/channels/{short.channel.id}"
								class="pointer-events-auto text-sm font-semibold hover:underline"
							>
								{short.channel.name ?? short.channel.handle}
							</a>
						{/if}
						<p class="mt-1 line-clamp-2 text-sm">{short.title}</p>
					</div>

					<div class="absolute top-3 right-3 flex flex-col items-end gap-2">
						<div class="flex items-center gap-1 rounded-full bg-black/50 pl-3 text-white">
							<input
								type="range"
								min="0"
								max="1"
								step="0.01"
								value={muted ? 0 : volume}
								oninput={(e) => setVolume(Number(e.currentTarget.value))}
								class="h-1 w-20 cursor-pointer accent-primary sm:w-24"
								aria-label="Volume"
							/>
							<Button
								size="icon"
								variant="ghost"
								class="rounded-full hover:bg-white/20 hover:text-white"
								aria-label={muted ? 'Unmute' : 'Mute'}
								onclick={toggleMute}
							>
								{#if muted || volume === 0}<VolumeXIcon />{:else}<Volume2Icon />{/if}
							</Button>
						</div>
						<Button
							size="icon"
							variant="secondary"
							class="rounded-full bg-black/50 text-white hover:bg-black/70"
							aria-label="Open on its own page"
							href="/watch/{short.id}"
						>
							<ExternalLinkIcon />
						</Button>
					</div>

					{#if i === active}
						<div class="absolute inset-x-0 bottom-0 h-1 bg-white/25">
							<div class="h-full bg-brand-red" style:width="{progress * 100}%"></div>
						</div>
					{/if}
				</section>
			{/each}
		</div>

		<div class="absolute top-1/2 -right-14 hidden -translate-y-1/2 flex-col gap-2 md:flex">
			<Button
				size="icon"
				variant="outline"
				class="rounded-full"
				aria-label="Previous short"
				disabled={active <= 0}
				onclick={() => go(-1)}><ChevronUpIcon /></Button
			>
			<Button
				size="icon"
				variant="outline"
				class="rounded-full"
				aria-label="Next short"
				disabled={active >= items.length - 1}
				onclick={() => go(1)}><ChevronDownIcon /></Button
			>
		</div>
	</div>
{/if}
