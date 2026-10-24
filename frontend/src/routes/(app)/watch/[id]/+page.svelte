<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Switch } from '#lib/components/ui/switch/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { api, call, errorMessage, mediaUrl, type Video } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { ago, bytes, calendarDate, count } from '#lib/format.js';
	import Player, { type Track } from '#lib/components/app/player.svelte';
	import Description from '#lib/components/app/description.svelte';
	import VideoCard from '#lib/components/app/video-card.svelte';
	import VideoMenu from '#lib/components/app/video-menu.svelte';
	import ChannelAvatar from '#lib/components/app/channel-avatar.svelte';
	import EmptyState from '#lib/components/app/empty-state.svelte';
	import EyeIcon from '@lucide/svelte/icons/eye';
	import CheckIcon from '@lucide/svelte/icons/check';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import DownloadIcon from '@lucide/svelte/icons/download';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import ListVideoIcon from '@lucide/svelte/icons/list-video';
	import FilmIcon from '@lucide/svelte/icons/film';
	import CaptionsIcon from '@lucide/svelte/icons/captions';

	const SAVE_EVERY = 10; // seconds of playback between progress saves
	const AUTOPLAY_KEY = 'lones-vdl:autoplay';
	const COUNTDOWN = 5;

	const queryClient = useQueryClient();
	const id = $derived(Number(page.params.id));
	const collectionId = $derived(Number(page.url.searchParams.get('collection')) || null);

	const video = createQuery(() => queries.video(id));
	const related = createQuery(() => queries.related(id));
	const collection = createQuery(() => ({
		...queries.collection(collectionId ?? 0),
		enabled: collectionId !== null
	}));

	// The detail query refetches on live events; only render once it matches this URL.
	const current = $derived(video.data?.id === id ? video.data : undefined);

	const inCollection = $derived(
		collectionId !== null && collection.data?.videos.some((v) => v.id === id)
	);
	const next = $derived.by((): Video | null | undefined => {
		if (inCollection && collection.data) {
			const list = collection.data.videos;
			return list[list.findIndex((v) => v.id === id) + 1] ?? null;
		}
		return related.data?.up_next;
	});
	const hrefFor = (v: Video) =>
		`/watch/${v.id}${inCollection ? `?collection=${collectionId}` : ''}`;

	/** Resume where the user left off, unless they finished it (or the URL says ?t=). */
	function startFor(v: NonNullable<typeof current>): number {
		const t = Number(page.url.searchParams.get('t'));
		if (t > 0) return t;
		const pos = v.position_seconds ?? 0;
		const dur = v.duration_seconds ?? 0;
		return !v.watched && pos > 5 && (!dur || pos < dur - Math.min(15, dur * 0.1)) ? pos : 0;
	}

	const languages = new Intl.DisplayNames(undefined, { type: 'language' });
	function languageLabel(code: string) {
		const original = code.endsWith('-orig');
		const base = code.replace(/-orig$/, '');
		let name = base;
		try {
			name = languages.of(base) ?? base;
		} catch {
			// not a valid BCP 47 tag; show the code
		}
		return original ? `${name} (original)` : name;
	}
	const tracks = $derived<Track[]>(
		(current?.subtitles ?? []).map((lang) => ({
			lang,
			label: languageLabel(lang),
			src: mediaUrl.subtitle(id, lang)
		}))
	);

	// Declared before the effects below, which run during setup when the video is already cached
	// (coming back with the browser's back button) and need these.
	let autoplay = $state(readAutoplay());
	let countdown = $state<number | null>(null);
	let timer: ReturnType<typeof setInterval> | undefined;

	// --- Progress saving -------------------------------------------------------------------
	let player = $state<ReturnType<typeof Player>>();
	let lastSaved = 0;
	let lastPosition = 0;
	let crossedWatched = false;
	let savingFor = 0; // the video the counters above belong to

	function save(position: number, keepalive = false) {
		if (!savingFor) return;
		lastSaved = position;
		api
			.PUT('/api/videos/{video_pk}/progress', {
				params: { path: { video_pk: savingFor } },
				body: { position_seconds: position },
				keepalive
			})
			.catch(() => {}); // progress is best-effort; the next save catches up
	}

	function ontime(position: number, duration: number) {
		lastPosition = position;
		if (Math.abs(position - lastSaved) >= SAVE_EVERY) save(position);
		if (!crossedWatched && duration && position >= duration * 0.9) {
			crossedWatched = true;
			save(position);
			setTimeout(() => queryClient.invalidateQueries({ queryKey: keys.video(savingFor) }), 500);
		}
	}

	function flush(keepalive = true) {
		if (savingFor && lastPosition && Math.abs(lastPosition - lastSaved) >= 1)
			save(lastPosition, keepalive);
	}

	// A new video: flush the old one's position, reset counters.
	$effect.pre(() => {
		const nextId = current?.id;
		if (!nextId || nextId === savingFor) return;
		flush(false);
		queryClient.invalidateQueries({ queryKey: keys.continueWatching });
		savingFor = nextId;
		lastSaved = lastPosition = startFor(current);
		crossedWatched = false;
		cancelCountdown();
	});

	onDestroy(() => {
		flush();
		cancelCountdown();
		// Home and the library show progress bars; refresh them with what was just watched.
		queryClient.invalidateQueries({ queryKey: keys.videos });
	});

	function onvisibility() {
		if (document.visibilityState === 'hidden') flush();
	}

	// --- Up next / autoplay ----------------------------------------------------------------
	function readAutoplay() {
		try {
			return localStorage.getItem(AUTOPLAY_KEY) !== 'off';
		} catch {
			return true;
		}
	}
	function setAutoplay(value: boolean) {
		autoplay = value;
		try {
			localStorage.setItem(AUTOPLAY_KEY, value ? 'on' : 'off');
		} catch {
			// storage unavailable; the choice lasts for this page only
		}
		if (!value) cancelCountdown();
	}

	function cancelCountdown() {
		clearInterval(timer);
		timer = undefined;
		countdown = null;
	}

	function onended() {
		const duration = current?.duration_seconds;
		save(duration ?? lastPosition);
		queryClient.invalidateQueries({ queryKey: keys.video(id) });
		if (!autoplay || !next) return;
		const target = hrefFor(next);
		countdown = COUNTDOWN;
		timer = setInterval(() => {
			if (countdown === null) return;
			countdown -= 1;
			if (countdown <= 0) {
				cancelCountdown();
				goto(target);
			}
		}, 1000);
	}

	// --- Actions ---------------------------------------------------------------------------
	const setWatched = createMutation(() => ({
		mutationFn: (watched: boolean) =>
			call(
				api.PUT('/api/videos/{video_pk}/watched', {
					params: { path: { video_pk: id } },
					body: { watched }
				})
			),
		onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.videos }),
		onError: (e) => toast.error(e.message)
	}));

	// Subtitles are not fetched while archiving; this asks for them (a job under Downloads).
	let subtitlesRequestedFor = $state(0);
	const fetchSubtitles = createMutation(() => ({
		mutationFn: () =>
			call(api.POST('/api/videos/{video_pk}/subtitles', { params: { path: { video_pk: id } } })),
		onSuccess: () => {
			subtitlesRequestedFor = id;
			queryClient.invalidateQueries({ queryKey: keys.jobs });
			toast.success('Fetching subtitles', {
				description: 'They appear here when the download finishes. Progress is under Downloads.'
			});
		},
		onError: (e) => toast.error(e.message)
	}));

	let expanded = $state(false);

	const facts = $derived.by(() => {
		if (!current) return [];
		return [
			current.view_count != null && count(current.view_count, 'view'),
			current.upload_date && calendarDate(current.upload_date),
			current.height && `${current.height}p`,
			current.media_size && bytes(current.media_size),
			`archived ${ago(current.archived_at)}`
		].filter(Boolean) as string[];
	});
</script>

<svelte:head><title>{current?.title ?? 'Watch'} · Lones-VDL</title></svelte:head>
<svelte:document onvisibilitychange={onvisibility} />
<svelte:window onpagehide={() => flush()} />

<div
	class="mx-auto grid max-w-[110rem] gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] 2xl:grid-cols-[minmax(0,1fr)_26rem]"
>
	<div class="min-w-0 space-y-4">
		{#if video.isError}
			<EmptyState
				icon={FilmIcon}
				title="Couldn't open this video"
				description={errorMessage(video.error)}
			>
				<Button variant="outline" href="/library">Back to library</Button>
			</EmptyState>
		{:else if !current}
			<Skeleton class="aspect-video w-full rounded-xl" />
			<Skeleton class="h-7 w-2/3" />
			<Skeleton class="h-10 w-1/3" />
		{:else}
			{#if current.integrity === 'missing'}
				<Alert.Root variant="destructive">
					<TriangleAlertIcon />
					<Alert.Title>The media file is missing</Alert.Title>
					<Alert.Description>
						It was not found on the archive share during the last check. Re-add the video by URL to
						download it again.
					</Alert.Description>
				</Alert.Root>
			{/if}

			<div class="relative -mx-4 overflow-hidden sm:mx-0 sm:rounded-xl">
				{#key current.id}
					<Player
						bind:this={player}
						src={mediaUrl.video(current.id)}
						poster={current.has_thumbnail ? mediaUrl.thumbnail(current.id) : undefined}
						{tracks}
						startAt={startFor(current)}
						autoplay
						{ontime}
						onpause={(p) => save(p)}
						{onended}
					/>
				{/key}
				{#if countdown !== null && next}
					<div
						class="absolute inset-0 z-10 grid place-items-center bg-black/75 p-4 text-white backdrop-blur-sm"
					>
						<div class="w-full max-w-sm space-y-4 text-center">
							<p class="text-sm text-white/70">Up next in {countdown}</p>
							<p class="line-clamp-2 text-lg font-semibold">{next.title}</p>
							<div class="flex justify-center gap-2">
								<Button variant="secondary" onclick={cancelCountdown}>Cancel</Button>
								<Button onclick={() => goto(hrefFor(next))}>Play now</Button>
							</div>
						</div>
					</div>
				{/if}
			</div>

			<div class="space-y-3">
				<h1 class="text-xl leading-snug font-semibold sm:text-2xl">{current.title}</h1>

				<div class="flex flex-wrap items-center justify-between gap-3">
					{#if current.channel}
						<a href="/channels/{current.channel.id}" class="group flex min-w-0 items-center gap-3">
							<ChannelAvatar channel={current.channel} class="size-10" />
							<div class="min-w-0">
								<p class="truncate font-medium group-hover:text-primary">
									{current.channel.name ?? current.channel.handle}
								</p>
								{#if current.channel.handle && current.channel.name}
									<p class="truncate text-xs text-muted-foreground">{current.channel.handle}</p>
								{/if}
							</div>
						</a>
					{/if}

					<div class="flex flex-wrap items-center gap-2">
						<Button
							variant={current.watched ? 'secondary' : 'outline'}
							size="sm"
							onclick={() => setWatched.mutate(!current.watched)}
							disabled={setWatched.isPending}
						>
							{#if current.watched}<CheckIcon /> Watched{:else}<EyeIcon /> Mark watched{/if}
						</Button>
						{#if !current.subtitles?.length}
							<Button
								variant="outline"
								size="sm"
								onclick={() => fetchSubtitles.mutate()}
								disabled={fetchSubtitles.isPending || subtitlesRequestedFor === id}
							>
								<CaptionsIcon />
								<span class="hidden sm:inline">
									{subtitlesRequestedFor === id ? 'Subtitles requested' : 'Get subtitles'}
								</span>
							</Button>
						{/if}
						<Button variant="outline" size="sm" href={mediaUrl.video(current.id)} download>
							<DownloadIcon /> <span class="hidden sm:inline">File</span>
						</Button>
						{#if current.source_url}
							<Button
								variant="outline"
								size="sm"
								href={current.source_url}
								target="_blank"
								rel="noopener noreferrer"
							>
								<ExternalLinkIcon /> <span class="hidden sm:inline">Original</span>
							</Button>
						{/if}
						<VideoMenu video={current} ondeleted={() => goto('/library')} />
					</div>
				</div>

				<div class="rounded-xl bg-muted/50 p-3 sm:p-4">
					<div class="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium">
						{#each facts as fact, i (fact)}
							{#if i}<span class="text-muted-foreground">·</span>{/if}<span>{fact}</span>
						{/each}
						{#if current.integrity === 'mismatch'}
							<Badge variant="destructive">Checksum changed</Badge>
						{/if}
						{#if current.content_kind !== 'video'}
							<Badge variant="secondary" class="capitalize">{current.content_kind}</Badge>
						{/if}
					</div>
					{#if current.description}
						<div class={[!expanded && 'line-clamp-4']}>
							<Description text={current.description} onseek={(s) => player?.seek(s)} />
						</div>
						<button
							type="button"
							class="mt-2 text-sm font-medium text-muted-foreground hover:text-foreground"
							onclick={() => (expanded = !expanded)}
						>
							{expanded ? 'Show less' : 'Show more'}
						</button>
					{:else}
						<p class="text-sm text-muted-foreground">No description.</p>
					{/if}
					{#if current.tags?.length}
						<!-- Links show every video with the tag, even ones the default preset hides. -->
						<ul class="mt-3 flex flex-wrap gap-1.5" aria-label="Tags">
							{#each current.tags as tag (tag)}
								<li>
									<Badge
										variant="outline"
										class="hover:bg-muted"
										href="/library?tag={encodeURIComponent(tag)}&preset=none">{tag}</Badge
									>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<aside class="min-w-0 space-y-6">
		{#if inCollection && collection.data}
			<section class="overflow-hidden rounded-xl border">
				<a
					href="/collections/{collection.data.id}"
					class="flex items-center gap-2 border-b bg-muted/40 px-4 py-3 hover:bg-muted"
				>
					<ListVideoIcon class="size-4 text-primary" />
					<span class="min-w-0 flex-1 truncate font-medium">{collection.data.name}</span>
					<span class="text-xs text-muted-foreground tabular-nums">
						{collection.data.videos.findIndex((v) => v.id === id) + 1} / {collection.data.videos
							.length}
					</span>
				</a>
				<ol class="max-h-96 space-y-1 overflow-y-auto p-2">
					{#each collection.data.videos as item, i (item.id)}
						<li>
							<a
								href={hrefFor(item)}
								aria-current={item.id === id ? 'true' : undefined}
								class="flex items-center gap-2 rounded-lg p-1.5 text-sm hover:bg-muted aria-[current]:bg-primary/10"
							>
								<span class="w-5 shrink-0 text-center text-xs text-muted-foreground tabular-nums"
									>{i + 1}</span
								>
								<span class="aspect-video w-20 shrink-0 overflow-hidden rounded-md bg-muted">
									{#if item.has_thumbnail}
										<img
											src={mediaUrl.thumbnail(item.id)}
											alt=""
											loading="lazy"
											class="size-full object-cover"
										/>
									{/if}
								</span>
								<span class="line-clamp-2 min-w-0 flex-1">{item.title}</span>
							</a>
						</li>
					{/each}
				</ol>
			</section>
		{/if}

		{#if next || related.data?.more_from_channel.length}
			<section class="space-y-3">
				<div class="flex items-center justify-between gap-2">
					<h2 class="font-semibold">Up next</h2>
					<div class="flex items-center gap-2">
						<Label for="autoplay" class="text-sm font-normal text-muted-foreground">Autoplay</Label>
						<Switch id="autoplay" checked={autoplay} onCheckedChange={setAutoplay} />
					</div>
				</div>
				{#if next}
					<VideoCard video={next} href={hrefFor(next)} compact />
				{:else if inCollection}
					<p class="text-sm text-muted-foreground">This is the last video in the collection.</p>
				{/if}
			</section>
		{/if}

		{#if related.data?.more_from_channel.length}
			<section class="space-y-3">
				<h2 class="font-semibold">More from this channel</h2>
				<div class="space-y-3">
					{#each related.data.more_from_channel as item (item.id)}
						<VideoCard video={item} compact showChannel={false} />
					{/each}
				</div>
			</section>
		{/if}
	</aside>
</div>
