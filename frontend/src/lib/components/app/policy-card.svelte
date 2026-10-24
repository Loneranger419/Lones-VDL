<!--
	How much of each site's daily download limits is used, whether downloads are paused, and how
	often the site let the app in without an account. Every site has its own card, because every
	site has its own limits (set in Settings).
-->
<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import * as Card from '#lib/components/ui/card/index.js';
	import { Progress } from '#lib/components/ui/progress/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { queries } from '#lib/api/queries.js';
	import type { PolicyStatus } from '#lib/api/client.js';
	import { ago } from '#lib/format.js';

	type Site = PolicyStatus['platforms'][number];
	type Group = Site['groups'][number];

	const policy = createQuery(() => queries.policy());

	const isPaused = (site: Site) =>
		!!site.paused_until && new Date(site.paused_until).getTime() > Date.now();
	const percent = (used: number, cap: number) => (cap ? Math.min((used / cap) * 100, 100) : 100);
	const anonymousTotal = (site: Site) =>
		site.anonymous_ok_7d + site.anonymous_refused_7d + site.anonymous_other_7d;
	const fullGroups = (site: Site) => site.groups.filter((g) => g.used >= g.cap);
</script>

{#snippet usage(label: string, used: number, cap: number, warn: boolean, small = false)}
	<div class={small ? 'space-y-1 pl-3' : 'space-y-1.5'}>
		<div class={['flex justify-between', small ? 'text-xs' : 'text-sm']}>
			<span class={small ? 'text-muted-foreground' : ''}>{label}</span>
			<span class="text-muted-foreground tabular-nums">{used} of {cap}</span>
		</div>
		<Progress
			value={percent(used, cap)}
			class={['h-1.5', warn && '[&>[data-slot=progress-indicator]]:bg-warning']}
		/>
	</div>
{/snippet}

{#snippet group(g: Group)}
	<div class="space-y-2.5">
		{@render usage(g.label, g.used, g.cap, g.used >= g.cap)}
		{@render usage('Using an account', g.auth_used, g.auth_cap, g.auth_used >= g.auth_cap, true)}
	</div>
{/snippet}

<div class="space-y-3">
	{#if !policy.data}
		<Skeleton class="h-48 w-full rounded-xl" />
	{:else}
		{#each policy.data.platforms as site (site.platform)}
			<Card.Root>
				<Card.Header>
					<Card.Title>{site.label} limits</Card.Title>
					<Card.Description>
						One download at a time, with a pause after each. Limits cover any rolling 24 hours and
						change in Settings.
					</Card.Description>
				</Card.Header>
				<Card.Content class="space-y-4">
					{#if isPaused(site)}
						<p class="rounded-lg bg-warning/10 p-3 text-sm">
							<strong
								>Paused until {new Date(site.paused_until ?? 0).toLocaleTimeString([], {
									hour: 'numeric',
									minute: '2-digit'
								})}.</strong
							>
							{site.pause_reason ?? `${site.label} limited requests.`}
							Waiting does not switch accounts.
						</p>
					{:else if fullGroups(site).length}
						<p class="rounded-lg bg-muted p-3 text-sm">
							Daily limit reached for {fullGroups(site)
								.map((g) => g.label.toLowerCase())
								.join(' and ')}. Queued ones start again as earlier downloads leave the 24 hour
							window.
						</p>
					{:else if site.next_video_at}
						<p class="text-sm text-muted-foreground">
							Next download starts {ago(site.next_video_at)}.
						</p>
					{/if}

					{#each site.groups as g (g.key)}
						{@render group(g)}
					{/each}

					<p class="text-xs text-muted-foreground">
						{#if anonymousTotal(site)}
							Last 7 days without an account: {site.anonymous_ok_7d} worked, {site.anonymous_refused_7d}
							needed sign-in{site.anonymous_other_7d
								? `, ${site.anonymous_other_7d} failed for other reasons`
								: ''}.
						{:else}
							No downloads in the last 7 days yet.
						{/if}
						Shorts wait while a video or stream can run. These are starting points; no limit guarantees
						{site.label} won’t restrict an account.
					</p>
				</Card.Content>
			</Card.Root>
		{/each}
	{/if}
</div>
