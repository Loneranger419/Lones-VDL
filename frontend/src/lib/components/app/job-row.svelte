<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Tooltip from '#lib/components/ui/tooltip/index.js';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Progress } from '#lib/components/ui/progress/index.js';
	import { api, call, type Job } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { ROLE_LABELS } from '#lib/accounts.js';
	import { live } from '#lib/api/events.svelte.js';
	import { ago, bytes, duration, QUALITY_LABELS, speed } from '#lib/format.js';
	import JobLogDialog from './job-log-dialog.svelte';
	import FilmIcon from '@lucide/svelte/icons/film';
	import ListIcon from '@lucide/svelte/icons/list-video';
	import ShieldCheckIcon from '@lucide/svelte/icons/shield-check';
	import ScanIcon from '@lucide/svelte/icons/scan-search';
	import CaptionsIcon from '@lucide/svelte/icons/captions';
	import XIcon from '@lucide/svelte/icons/x';
	import RotateIcon from '@lucide/svelte/icons/rotate-ccw';
	import FileTextIcon from '@lucide/svelte/icons/file-text';
	import TrashIcon from '@lucide/svelte/icons/trash-2';
	import PlayIcon from '@lucide/svelte/icons/play';
	import KeyRoundIcon from '@lucide/svelte/icons/key-round';
	import ApproveIcon from '@lucide/svelte/icons/shield-check';

	let { job }: { job: Job } = $props();

	const queryClient = useQueryClient();
	let logOpen = $state(false);

	const KindIcon = $derived(
		{
			download: FilmIcon,
			expand: ListIcon,
			verify: ShieldCheckIcon,
			rescan: ScanIcon,
			subtitles: CaptionsIcon
		}[job.kind] ?? FilmIcon
	);
	const live_ = $derived(live.progress[job.id]);
	const percent = $derived((live_?.progress ?? job.progress ?? 0) * 100);

	const STAGES: Record<string, string> = {
		waiting: 'Starting…',
		resolving: 'Getting info…',
		downloading: 'Downloading',
		processing: 'Finishing up…'
	};

	const MODES: Record<string, string> = {
		all: 'Full listing',
		recent: 'Checking for new uploads',
		baseline: 'Marking existing videos as seen',
		meta: 'Fetching channel details'
	};

	const subtitle = $derived.by(() => {
		const parts: string[] = [];
		if (job.kind === 'expand') parts.push(MODES[String(job.options?.mode ?? 'all')] ?? 'Listing');
		else if (job.kind === 'download') parts.push(QUALITY_LABELS[job.quality] ?? job.quality);
		else if (job.kind === 'subtitles') parts.push('Subtitles');
		if (job.status === 'queued' && job.attempts > 0)
			parts.push(`retry ${job.attempts + 1}/${job.max_attempts}`);
		if (job.auth_tier === 1 && job.status !== 'completed') parts.push('alternate account');
		if (job.auth_tier === 2 && job.status !== 'completed') parts.push('personal account');
		if (job.finished_at) parts.push(ago(job.finished_at));
		else if (job.status === 'queued') parts.push(`added ${ago(job.created_at)}`);
		return parts.join(' · ');
	});

	const resultText = $derived.by(() => {
		const r = job.result as Record<string, unknown> | null;
		if (!r || job.status !== 'completed') return '';
		if (job.kind === 'expand') {
			const bits = [`${r.found ?? 0} found`, `${r.queued ?? 0} queued`];
			if (r.known) bits.push(`${r.known} already archived`);
			if (r.ignored) bits.push(`${r.ignored} marked as seen`);
			return bits.join(', ');
		}
		if (job.kind === 'subtitles') return 'Subtitles added';
		if (job.kind === 'verify') {
			return `${r.checked ?? 0} checked: ${r.ok ?? 0} OK, ${r.mismatch ?? 0} changed, ${r.missing ?? 0} missing`;
		}
		if (job.kind === 'rescan') {
			return `${r.scanned ?? 0} folders: ${r.indexed ?? 0} added, ${r.missing ?? 0} missing, ${r.relinked ?? 0} relinked`;
		}
		return '';
	});

	type Action = { kind: 'cancel' | 'retry' | 'delete' | 'approve'; accountId?: number };

	function act({ kind, accountId }: Action) {
		const params = { params: { path: { job_id: job.id } } };
		if (kind === 'delete') return call(api.DELETE('/api/jobs/{job_id}', params));
		if (kind === 'cancel') return call(api.POST('/api/jobs/{job_id}/cancel', params));
		if (kind === 'approve') return call(api.POST('/api/jobs/{job_id}/approve', params));
		return call(
			api.POST('/api/jobs/{job_id}/retry', {
				...params,
				body: accountId === undefined ? undefined : { account_id: accountId }
			})
		);
	}

	// Accounts a failed job can be retried with. The personal account is for single videos only.
	const accounts = createQuery(() => ({
		...queries.accounts(),
		enabled: job.status === 'failed' || job.status === 'cancelled'
	}));
	const retryAccounts = $derived(
		(accounts.data ?? []).filter(
			(a) => a.enabled && a.status.present && (a.role === 'alternate' || job.kind === 'download')
		)
	);

	const action = createMutation(() => ({
		mutationFn: act,
		onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.jobs }),
		onError: (e) => toast.error(e.message)
	}));

	const tone = $derived(
		{
			running: 'bg-primary/15 text-primary',
			queued: 'bg-muted text-muted-foreground',
			awaiting_approval: 'bg-warning/15 text-warning',
			completed: 'bg-success/15 text-success',
			failed: 'bg-brand-red/15 text-brand-red',
			cancelled: 'bg-muted text-muted-foreground'
		}[job.status] ?? 'bg-muted'
	);
</script>

{#snippet iconButton(label: string, Icon: typeof XIcon, onclick: () => void, href?: string)}
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}
				{#if href}
					<Button {...props} {href} variant="ghost" size="icon-sm" aria-label={label}
						><Icon /></Button
					>
				{:else}
					<Button
						{...props}
						variant="ghost"
						size="icon-sm"
						aria-label={label}
						disabled={action.isPending}
						{onclick}
					>
						<Icon />
					</Button>
				{/if}
			{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Content>{label}</Tooltip.Content>
	</Tooltip.Root>
{/snippet}

<li class="flex gap-3 px-3 py-3 sm:px-4">
	<div class={['mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg', tone]}>
		<KindIcon
			class={['size-4.5', job.status === 'running' && job.kind !== 'download' && 'animate-pulse']}
		/>
	</div>

	<div class="min-w-0 flex-1 space-y-1">
		<div class="flex items-baseline gap-2">
			<p class="truncate text-sm font-medium" title={job.url}>
				{#if job.video_pk && job.status === 'completed'}
					<a href="/watch/{job.video_pk}" class="hover:text-primary">{job.title ?? job.video_id}</a>
				{:else if job.channel_pk && job.kind === 'expand'}
					<a href="/channels/{job.channel_pk}" class="hover:text-primary">{job.title ?? job.url}</a>
				{:else}
					{job.title ?? job.video_id ?? job.url}
				{/if}
			</p>
		</div>
		<p class="truncate text-xs text-muted-foreground">{subtitle}</p>

		{#if job.status === 'running'}
			{#if job.kind === 'download' && (live_?.stage ?? job.stage) === 'downloading'}
				<Progress value={percent} class="h-1.5" />
				<p class="text-xs text-muted-foreground tabular-nums">
					{percent.toFixed(0)}%
					{#if live_?.total_bytes}· {bytes(live_.downloaded_bytes)} of {bytes(
							live_.total_bytes
						)}{/if}
					{#if live_?.speed}· {speed(live_.speed)}{/if}
					{#if live_?.eta}· {duration(live_.eta)} left{/if}
				</p>
			{:else if (job.kind === 'verify' || job.kind === 'rescan') && percent > 0}
				<Progress value={percent} class="h-1.5" />
			{:else}
				<p class="text-xs text-primary">{STAGES[live_?.stage ?? job.stage] ?? 'Working…'}</p>
			{/if}
		{:else if job.status === 'awaiting_approval'}
			<p class="text-xs text-warning">{job.error_message}</p>
		{:else if job.status === 'failed' || (job.status === 'queued' && job.error_message)}
			<p class="text-xs text-brand-red">
				{job.status === 'queued'
					? `Will retry ${ago(job.next_attempt_at)}: `
					: ''}{job.error_message}
			</p>
		{:else if resultText}
			<p class="text-xs text-muted-foreground">{resultText}</p>
		{/if}
	</div>

	<div class="flex shrink-0 items-start gap-0.5">
		{#if job.status === 'completed' && job.video_pk}
			{@render iconButton('Watch', PlayIcon, () => {}, `/watch/${job.video_pk}`)}
		{/if}
		{#if job.status === 'awaiting_approval'}
			<Button
				size="sm"
				variant="outline"
				disabled={action.isPending}
				onclick={() => action.mutate({ kind: 'approve' })}
			>
				<ApproveIcon /> Approve
			</Button>
		{/if}
		{#if job.status === 'queued' || job.status === 'running' || job.status === 'awaiting_approval'}
			{@render iconButton('Cancel', XIcon, () => action.mutate({ kind: 'cancel' }))}
		{/if}
		{#if job.status === 'failed' || job.status === 'cancelled'}
			{@render iconButton('Retry', RotateIcon, () => action.mutate({ kind: 'retry' }))}
			{#if retryAccounts.length}
				<DropdownMenu.Root>
					<DropdownMenu.Trigger>
						{#snippet child({ props })}
							<Button
								{...props}
								variant="ghost"
								size="icon-sm"
								aria-label="Retry with an account"
								title="Retry with an account"
								disabled={action.isPending}
							>
								<KeyRoundIcon />
							</Button>
						{/snippet}
					</DropdownMenu.Trigger>
					<DropdownMenu.Content align="end" class="w-60">
						<DropdownMenu.Label>Retry signed in as…</DropdownMenu.Label>
						{#each retryAccounts as account (account.id)}
							<DropdownMenu.Item
								onclick={() => action.mutate({ kind: 'retry', accountId: account.id })}
							>
								{account.label}
								<span class="ml-auto text-xs text-muted-foreground"
									>{ROLE_LABELS[account.role]}</span
								>
							</DropdownMenu.Item>
						{/each}
					</DropdownMenu.Content>
				</DropdownMenu.Root>
			{/if}
		{/if}
		{#if job.attempts > 0}
			{@render iconButton('Log', FileTextIcon, () => (logOpen = true))}
		{/if}
		{#if job.status !== 'queued' && job.status !== 'running' && job.status !== 'awaiting_approval'}
			{@render iconButton('Remove from list', TrashIcon, () => action.mutate({ kind: 'delete' }))}
		{/if}
	</div>
</li>

{#if logOpen}
	<JobLogDialog {job} bind:open={logOpen} />
{/if}
