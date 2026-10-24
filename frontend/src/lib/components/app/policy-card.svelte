<!--
	How much of the daily download limits is used, whether downloads are paused, and how often
	YouTube let the app in without an account. The limits are set in Settings.
-->
<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import * as Card from '#lib/components/ui/card/index.js';
	import { Progress } from '#lib/components/ui/progress/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { queries } from '#lib/api/queries.js';
	import { ago } from '#lib/format.js';

	const policy = createQuery(() => queries.policy());
	const p = $derived(policy.data);

	const anonymousTotal = $derived(
		p ? p.anonymous_ok_7d + p.anonymous_refused_7d + p.anonymous_other_7d : 0
	);
	const paused = $derived(!!p?.paused_until && new Date(p.paused_until).getTime() > Date.now());
	const full = $derived(!!p && p.downloads_24h >= p.daily_download_cap);
	const authFull = $derived(!!p && p.authenticated_24h >= p.daily_auth_cap);
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Download limits</Card.Title>
		<Card.Description>
			One video at a time, with a short pause after each. Limits cover any rolling 24 hours and
			change in Settings.
		</Card.Description>
	</Card.Header>
	<Card.Content class="space-y-4">
		{#if !p}
			<Skeleton class="h-24 w-full" />
		{:else}
			{#if paused}
				<p class="rounded-lg bg-warning/10 p-3 text-sm">
					<strong
						>Paused until {new Date(p.paused_until ?? 0).toLocaleTimeString([], {
							hour: 'numeric',
							minute: '2-digit'
						})}.</strong
					>
					{p.pause_reason ?? 'YouTube limited requests.'}
					Waiting does not switch accounts.
				</p>
			{:else if full}
				<p class="rounded-lg bg-muted p-3 text-sm">
					Daily limit reached. Queued videos start again as earlier downloads leave the 24 hour
					window.
				</p>
			{:else if p.next_video_at}
				<p class="text-sm text-muted-foreground">Next video starts {ago(p.next_video_at)}.</p>
			{/if}

			<div class="space-y-1.5">
				<div class="flex justify-between text-sm">
					<span>Videos</span>
					<span class="text-muted-foreground tabular-nums">
						{p.downloads_24h} of {p.daily_download_cap}
					</span>
				</div>
				<Progress value={(p.downloads_24h / p.daily_download_cap) * 100} class="h-1.5" />
			</div>
			<div class="space-y-1.5">
				<div class="flex justify-between text-sm">
					<span>Using an account</span>
					<span class="text-muted-foreground tabular-nums">
						{p.authenticated_24h} of {p.daily_auth_cap}
					</span>
				</div>
				<Progress
					value={p.daily_auth_cap ? (p.authenticated_24h / p.daily_auth_cap) * 100 : 100}
					class={['h-1.5', authFull && '[&>[data-slot=progress-indicator]]:bg-warning']}
				/>
			</div>

			<p class="text-xs text-muted-foreground">
				{#if anonymousTotal}
					Last 7 days without an account: {p.anonymous_ok_7d} worked, {p.anonymous_refused_7d} needed
					sign-in{p.anonymous_other_7d ? `, ${p.anonymous_other_7d} failed for other reasons` : ''}.
				{:else}
					No downloads in the last 7 days yet.
				{/if}
				These are starting points; no limit guarantees YouTube won’t restrict an account.
			</p>
		{/if}
	</Card.Content>
</Card.Root>
