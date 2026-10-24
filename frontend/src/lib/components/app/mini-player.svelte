<!--
	A small player in the corner for the video that was playing when you left its Watch page. It
	carries on from the same position, saves progress like the Watch page does, and goes away when
	you close it, it ends, or you open any video.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, untrack } from 'svelte';
	import { api } from '#lib/api/client.js';
	import { mini } from '#lib/mini-player.svelte.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import Player from '#lib/components/app/player.svelte';
	import ExpandIcon from '@lucide/svelte/icons/maximize-2';
	import XIcon from '@lucide/svelte/icons/x';

	const SAVE_EVERY = 10; // seconds of playback between progress saves

	const video = $derived(mini.video);
	let position = 0;
	let lastSaved = 0;
	let player = $state<ReturnType<typeof Player>>();

	function save(keepalive = false) {
		if (!video) return;
		lastSaved = position;
		api
			.PUT('/api/videos/{video_pk}/progress', {
				params: { path: { video_pk: video.id } },
				body: { position_seconds: position },
				keepalive
			})
			.catch(() => {}); // best effort, like on the Watch page
	}

	// Each video starts its counters from where it was handed over.
	$effect(() => {
		position = lastSaved = video?.position ?? 0;
	});

	function ontime(seconds: number) {
		position = seconds;
		if (Math.abs(position - lastSaved) >= SAVE_EVERY) save();
	}

	function close() {
		if (Math.abs(position - lastSaved) >= 1) save();
		mini.video = null;
	}

	function expand() {
		if (!video) return;
		const target = `/watch/${video.id}?t=${Math.floor(player?.position() ?? position)}`;
		goto(target);
	}

	// Opening any video takes over from the floating one.
	$effect(() => {
		if (page.url.pathname.startsWith('/watch/')) untrack(close);
	});

	onDestroy(() => {
		if (video && Math.abs(position - lastSaved) >= 1) save(true);
	});
</script>

<svelte:window onpagehide={() => video && Math.abs(position - lastSaved) >= 1 && save(true)} />

{#if video}
	{#key video.id}
		<section
			class="fixed right-3 bottom-[calc(var(--bottom-nav-height)+0.75rem)] z-50 w-[min(20rem,calc(100vw-1.5rem))] overflow-hidden rounded-xl border bg-card shadow-2xl md:right-5 md:bottom-5"
			aria-label="Mini player"
		>
			<Player
				bind:this={player}
				src={video.src}
				poster={video.poster}
				tracks={video.tracks}
				startAt={video.position}
				autoplay
				{ontime}
				onpause={() => save()}
				onended={close}
			/>
			<div class="flex items-center gap-1 py-1 pr-1 pl-3">
				<button
					type="button"
					class="min-w-0 flex-1 truncate text-left text-sm font-medium hover:text-primary"
					onclick={expand}
				>
					{video.title}
				</button>
				<Button variant="ghost" size="icon-sm" aria-label="Open the video page" onclick={expand}>
					<ExpandIcon />
				</Button>
				<Button variant="ghost" size="icon-sm" aria-label="Close the mini player" onclick={close}>
					<XIcon />
				</Button>
			</div>
		</section>
	{/key}
{/if}
