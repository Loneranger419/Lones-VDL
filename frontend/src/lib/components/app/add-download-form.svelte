<script lang="ts">
	import { goto } from '$app/navigation';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Switch } from '#lib/components/ui/switch/index.js';
	import * as ToggleGroup from '#lib/components/ui/toggle-group/index.js';
	import { ApiError, api, call } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { QUALITY_LABELS } from '#lib/format.js';
	import SimpleSelect from './simple-select.svelte';
	import LinkIcon from '@lucide/svelte/icons/link';
	import LoaderIcon from '@lucide/svelte/icons/loader-circle';

	let { url = $bindable(''), onqueued }: { url?: string; onqueued?: () => void } = $props();

	let quality = $state('default');
	let watch = $state(true);
	let backfill = $state(true);
	let tabs = $state(['videos', 'streams']);

	const settings = createQuery(() => queries.settings());
	const queryClient = useQueryClient();

	/** Rough client-side guess, only to show the right options; the server decides. */
	function kindOf(text: string): 'video' | 'playlist' | 'channel' | null {
		const value = text.trim();
		if (!value) return null;
		if (/[?&]list=/.test(value) && /\/playlist\b/.test(value)) return 'playlist';
		if (/youtu\.be\/|[?&]v=|\/(shorts|live|embed)\//.test(value)) return 'video';
		if (/youtube\.com\/(@|channel\/|c\/|user\/)/.test(value)) return 'channel';
		return 'video';
	}
	const kind = $derived(kindOf(url));

	const qualityOptions = $derived([
		{
			value: 'default',
			label: `Default (${QUALITY_LABELS[settings.data?.current.default_quality ?? 'best']})`
		},
		...Object.entries(QUALITY_LABELS).map(([value, label]) => ({ value, label }))
	]);

	const enqueue = createMutation(() => ({
		mutationFn: () =>
			call(
				api.POST('/api/jobs', {
					body: {
						url: url.trim(),
						quality: quality === 'default' ? null : quality,
						backfill: kind === 'channel' ? backfill : true,
						...(kind === 'channel' ? { watch, tabs } : {})
					}
				})
			),
		onSuccess: (job) => {
			queryClient.invalidateQueries({ queryKey: keys.jobs });
			const what =
				job.kind === 'expand'
					? kind === 'channel'
						? 'Listing the channel'
						: 'Listing the playlist'
					: 'Download queued';
			toast.success(what, {
				description: job.kind === 'expand' ? 'New videos will be queued automatically.' : undefined,
				action: { label: 'View', onClick: () => goto('/downloads') }
			});
			url = '';
			onqueued?.();
		},
		onError: (error) => {
			if (error instanceof ApiError && error.status === 409) {
				const videoPk = error.body.video_pk;
				toast.info(error.message, {
					action:
						typeof videoPk === 'number'
							? { label: 'Watch', onClick: () => goto(`/watch/${videoPk}`) }
							: { label: 'Downloads', onClick: () => goto('/downloads') }
				});
			} else {
				toast.error(error.message);
			}
		}
	}));

	function submit(event: SubmitEvent) {
		event.preventDefault();
		if (url.trim() && !enqueue.isPending) enqueue.mutate();
	}
</script>

<form onsubmit={submit} class="space-y-4">
	<div class="space-y-2">
		<Label for="add-url">Video, playlist, or channel URL</Label>
		<div class="relative">
			<LinkIcon
				class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
			/>
			<Input
				id="add-url"
				bind:value={url}
				placeholder="https://www.youtube.com/watch?v=…"
				class="h-10 pl-9"
				autocomplete="off"
				spellcheck={false}
				required
			/>
		</div>
	</div>

	<div class="flex flex-wrap items-end gap-4">
		<div class="space-y-2">
			<Label>Quality</Label>
			<SimpleSelect bind:value={quality} options={qualityOptions} class="w-52" label="Quality" />
		</div>
	</div>

	{#if kind === 'channel'}
		<div class="space-y-4 rounded-lg border bg-muted/30 p-4">
			<div class="flex items-start justify-between gap-4">
				<div>
					<Label for="add-watch">Auto-archive new uploads</Label>
					<p class="text-sm text-muted-foreground">
						Check this channel regularly and download new videos.
					</p>
				</div>
				<Switch id="add-watch" bind:checked={watch} />
			</div>
			<div class="flex items-start justify-between gap-4">
				<div>
					<Label for="add-backfill">Download existing videos</Label>
					<p class="text-sm text-muted-foreground">
						{backfill
							? 'The whole back catalogue is queued (lowest priority).'
							: 'Only videos uploaded from now on.'}
					</p>
				</div>
				<Switch id="add-backfill" bind:checked={backfill} />
			</div>
			<div class="space-y-2">
				<Label>Include</Label>
				<ToggleGroup.Root type="multiple" bind:value={tabs} variant="outline" size="sm">
					<ToggleGroup.Item value="videos">Videos</ToggleGroup.Item>
					<ToggleGroup.Item value="streams">Past streams</ToggleGroup.Item>
					<ToggleGroup.Item value="shorts">Shorts</ToggleGroup.Item>
				</ToggleGroup.Root>
			</div>
		</div>
	{:else if kind === 'playlist'}
		<p class="text-sm text-muted-foreground">
			Every video in the playlist that isn't archived yet will be queued.
		</p>
	{/if}

	<Button
		type="submit"
		disabled={!url.trim() || enqueue.isPending || (kind === 'channel' && !tabs.length)}
	>
		{#if enqueue.isPending}<LoaderIcon class="animate-spin" />{/if}
		{kind === 'channel' ? 'Add channel' : kind === 'playlist' ? 'Add playlist' : 'Download'}
	</Button>
</form>
