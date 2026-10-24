<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Card from '#lib/components/ui/card/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Progress } from '#lib/components/ui/progress/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { api, call, type DoctorReport } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { ago, bytes } from '#lib/format.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import AccountsPanel from '#lib/components/app/accounts-panel.svelte';
	import PolicyCard from '#lib/components/app/policy-card.svelte';
	import RefreshIcon from '@lucide/svelte/icons/refresh-cw';
	import LoaderIcon from '@lucide/svelte/icons/loader-circle';
	import ShieldCheckIcon from '@lucide/svelte/icons/shield-check';
	import ScanIcon from '@lucide/svelte/icons/scan-search';
	import StethoscopeIcon from '@lucide/svelte/icons/stethoscope';
	import CircleCheckIcon from '@lucide/svelte/icons/circle-check';
	import CircleAlertIcon from '@lucide/svelte/icons/circle-alert';
	import CircleXIcon from '@lucide/svelte/icons/circle-x';

	const queryClient = useQueryClient();
	const stats = createQuery(() => queries.stats());
	const ytdlp = createQuery(() => queries.ytdlp());

	const used = $derived(
		stats.data?.archive_total_bytes && stats.data.archive_free_bytes != null
			? stats.data.archive_total_bytes - stats.data.archive_free_bytes
			: null
	);
	const usedPercent = $derived(
		used != null && stats.data?.archive_total_bytes
			? (used / stats.data.archive_total_bytes) * 100
			: 0
	);

	const updateYtdlp = createMutation(() => ({
		mutationFn: () => call(api.POST('/api/system/ytdlp/update')),
		onSuccess: (status) => {
			queryClient.setQueryData(keys.ytdlp, status);
			if (status.last_error) toast.error('Update failed', { description: status.last_error });
			else toast.success(`yt-dlp ${status.version ?? ''} is installed`);
		},
		onError: (e) => toast.error(e.message)
	}));

	const maintenance = createMutation(() => ({
		mutationFn: (kind: 'verify' | 'rescan') =>
			kind === 'verify'
				? call(api.POST('/api/system/verify', { body: null }))
				: call(api.POST('/api/system/rescan')),
		onSuccess: (_, kind) => {
			queryClient.invalidateQueries({ queryKey: keys.jobs });
			toast.success(kind === 'verify' ? 'Verifying files' : 'Rescanning the archive', {
				description: 'Follow it in Downloads → Active.'
			});
		},
		onError: (e) => toast.error(e.message)
	}));

	let testUrl = $state('');
	let report = $state<DoctorReport | null>(null);
	const doctor = createMutation(() => ({
		mutationFn: () =>
			call(
				api.GET('/api/system/doctor', {
					params: { query: { url: testUrl.trim() || undefined } }
				})
			),
		onSuccess: (result) => (report = result),
		onError: (e) => toast.error(e.message)
	}));

	const CHECK_ICON = { ok: CircleCheckIcon, warn: CircleAlertIcon, fail: CircleXIcon };
	const CHECK_TONE = { ok: 'text-success', warn: 'text-warning', fail: 'text-brand-red' };

	const integrity = $derived(stats.data?.by_integrity ?? {});
</script>

<PageHeader
	title="Health"
	description="Storage, YouTube access, the downloader, and archive integrity."
/>

<div class="space-y-6">
	<!-- Overview -->
	<div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
		{#each [{ label: 'Videos', value: stats.data?.videos.toLocaleString() }, { label: 'Archived size', value: stats.data && bytes(stats.data.total_bytes) }, { label: 'Channels', value: stats.data && `${stats.data.channels}`, sub: stats.data && `${stats.data.watched_channels} auto-archiving` }, { label: 'Collections', value: stats.data && `${stats.data.collections}`, sub: stats.data && `${stats.data.creators} creators` }] as tile (tile.label)}
			<div class="rounded-xl border bg-card p-4">
				<p class="text-xs text-muted-foreground">{tile.label}</p>
				{#if tile.value === undefined}
					<Skeleton class="mt-1 h-7 w-16" />
				{:else}
					<p class="mt-0.5 text-2xl font-semibold tracking-tight tabular-nums">{tile.value}</p>
					{#if tile.sub}<p class="text-xs text-muted-foreground">{tile.sub}</p>{/if}
				{/if}
			</div>
		{/each}
	</div>

	{#if used != null && stats.data?.archive_total_bytes}
		<div class="rounded-xl border bg-card p-4">
			<div class="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
				<span class="font-medium">Archive storage</span>
				<span class="text-muted-foreground tabular-nums">
					{bytes(stats.data.archive_free_bytes)} free of {bytes(stats.data.archive_total_bytes)}
				</span>
			</div>
			<Progress
				value={usedPercent}
				class={['h-2', usedPercent > 90 && '[&>[data-slot=progress-indicator]]:bg-brand-red']}
			/>
		</div>
	{/if}

	<div class="grid gap-6 xl:grid-cols-2">
		<div class="space-y-6">
			<PolicyCard />
			<AccountsPanel />
		</div>

		<div class="space-y-6">
			<Card.Root>
				<Card.Header>
					<Card.Title>Downloader (yt-dlp)</Card.Title>
					<Card.Description>Kept up to date automatically; YouTube changes often.</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-3">
					{#if ytdlp.data}
						<dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
							<div>
								<dt class="text-muted-foreground">Version</dt>
								<dd class="font-mono">{ytdlp.data.version ?? 'not installed'}</dd>
							</div>
							<div>
								<dt class="text-muted-foreground">Channel</dt>
								<dd class="capitalize">{ytdlp.data.channel}</dd>
							</div>
							<div class="col-span-2">
								<dt class="text-muted-foreground">Last update check</dt>
								<dd>{ytdlp.data.last_checked_at ? ago(ytdlp.data.last_checked_at) : 'never'}</dd>
							</div>
						</dl>
						{#if ytdlp.data.last_error}
							<p class="text-sm break-words text-brand-red">{ytdlp.data.last_error}</p>
						{/if}
						{#if ytdlp.data.managed}
							<Button
								variant="outline"
								onclick={() => updateYtdlp.mutate()}
								disabled={updateYtdlp.isPending || ytdlp.data.updating}
							>
								{#if updateYtdlp.isPending || ytdlp.data.updating}
									<LoaderIcon class="animate-spin" /> Updating… (waits for running downloads)
								{:else}
									<RefreshIcon /> Update now
								{/if}
							</Button>
						{:else}
							<p class="text-sm text-muted-foreground">
								Using a system yt-dlp; update it outside the app.
							</p>
						{/if}
					{:else}
						<Skeleton class="h-20 w-full" />
					{/if}
				</Card.Content>
			</Card.Root>

			<Card.Root>
				<Card.Header>
					<Card.Title>Archive integrity</Card.Title>
					<Card.Description>
						Check files against the checksums saved at download time, or re-index the archive
						folder.
					</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-4">
					<div class="flex flex-wrap gap-x-5 gap-y-1 text-sm">
						<span><span class="font-medium tabular-nums">{integrity.ok ?? 0}</span> verified</span>
						<span class="text-muted-foreground">
							<span class="font-medium tabular-nums">{integrity.unverified ?? 0}</span> not checked yet
						</span>
						{#if integrity.mismatch}
							<span class="text-brand-red"
								><span class="font-medium tabular-nums">{integrity.mismatch}</span> changed</span
							>
						{/if}
						{#if integrity.missing}
							<span class="text-brand-red"
								><span class="font-medium tabular-nums">{integrity.missing}</span> missing</span
							>
						{/if}
					</div>
					{#if integrity.mismatch || integrity.missing}
						<Button
							variant="link"
							class="h-auto px-0"
							href="/library?integrity={integrity.missing ? 'missing' : 'mismatch'}"
						>
							Show affected videos
						</Button>
					{/if}
					<div class="flex flex-wrap gap-2">
						<Button
							variant="outline"
							onclick={() => maintenance.mutate('verify')}
							disabled={maintenance.isPending}
						>
							<ShieldCheckIcon /> Verify all files
						</Button>
						<Button
							variant="outline"
							onclick={() => maintenance.mutate('rescan')}
							disabled={maintenance.isPending}
						>
							<ScanIcon /> Rescan archive
						</Button>
					</div>
				</Card.Content>
			</Card.Root>
		</div>
	</div>

	<Card.Root>
		<Card.Header>
			<Card.Title>Diagnostics</Card.Title>
			<Card.Description>
				Checks the tools, cookies, and storage. Add a video URL to also test resolving it (nothing
				is downloaded).
			</Card.Description>
		</Card.Header>
		<Card.Content class="space-y-4">
			<form
				class="flex flex-col gap-2 sm:flex-row"
				onsubmit={(e) => {
					e.preventDefault();
					doctor.mutate();
				}}
			>
				<Input
					bind:value={testUrl}
					placeholder="Optional: https://www.youtube.com/watch?v=…"
					class="sm:flex-1"
				/>
				<Button type="submit" disabled={doctor.isPending}>
					{#if doctor.isPending}<LoaderIcon class="animate-spin" />{:else}<StethoscopeIcon />{/if}
					Run checks
				</Button>
			</form>
			{#if report}
				<ul class="divide-y rounded-lg border">
					{#each report.checks as check (check.name)}
						{@const Icon = CHECK_ICON[check.status as keyof typeof CHECK_ICON] ?? CircleAlertIcon}
						<li class="flex gap-3 p-3 text-sm">
							<Icon
								class={[
									'mt-0.5 size-4 shrink-0',
									CHECK_TONE[check.status as keyof typeof CHECK_TONE]
								]}
							/>
							<div class="min-w-0">
								<p class="font-medium">{check.name}</p>
								<p class="break-words whitespace-pre-wrap text-muted-foreground">{check.detail}</p>
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
