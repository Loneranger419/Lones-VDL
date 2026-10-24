<script lang="ts">
	import { page } from '$app/state';
	import { createQuery } from '@tanstack/svelte-query';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import { queries } from '#lib/api/queries.js';
	import { accountProblems, worstProblem } from '#lib/accounts.js';
	import { isActive, mainNav, systemNav, type NavItem } from '#lib/nav.js';
	import Logo from './logo.svelte';

	const counts = createQuery(() => queries.jobCounts());
	const accounts = createQuery(() => queries.accounts());

	const activeJobs = $derived((counts.data?.queued ?? 0) + (counts.data?.running ?? 0));
	const failedJobs = $derived(counts.data?.failed ?? 0);
	const awaiting = $derived(counts.data?.awaiting_approval ?? 0);
	const healthProblem = $derived(worstProblem(accountProblems(accounts.data)));
	const sidebar = Sidebar.useSidebar();
</script>

{#snippet item(nav: NavItem)}
	<Sidebar.MenuItem>
		<Sidebar.MenuButton isActive={isActive(page.url.pathname, nav)} tooltipContent={nav.label}>
			{#snippet child({ props })}
				<a href={nav.href} {...props} onclick={() => sidebar.setOpenMobile(false)}>
					<nav.icon />
					<span>{nav.label}</span>
				</a>
			{/snippet}
		</Sidebar.MenuButton>
		{#if nav.href === '/downloads' && awaiting}
			<Sidebar.MenuBadge class="bg-warning/15 text-warning">{awaiting}</Sidebar.MenuBadge>
		{:else if nav.href === '/downloads' && activeJobs}
			<Sidebar.MenuBadge class="bg-primary/15 text-primary">{activeJobs}</Sidebar.MenuBadge>
		{:else if nav.href === '/downloads' && failedJobs}
			<Sidebar.MenuBadge class="bg-destructive/15 text-destructive">{failedJobs}</Sidebar.MenuBadge>
		{:else if nav.href === '/health' && healthProblem}
			<Sidebar.MenuBadge>
				<span
					class={[
						'size-2 rounded-full',
						healthProblem.level === 'error' ? 'bg-brand-red' : 'bg-warning'
					]}
				></span>
			</Sidebar.MenuBadge>
		{/if}
	</Sidebar.MenuItem>
{/snippet}

<Sidebar.Root collapsible="icon">
	<Sidebar.Header>
		<a
			href="/"
			class="flex items-center gap-2.5 rounded-md p-1 group-data-[collapsible=icon]:p-0"
			aria-label="Lones-VDL home"
		>
			<Logo class="size-7" />
			<span class="truncate text-[0.95rem] font-semibold tracking-tight">Lones-VDL</span>
		</a>
	</Sidebar.Header>
	<Sidebar.Content>
		<Sidebar.Group>
			<Sidebar.GroupContent>
				<Sidebar.Menu>
					{#each mainNav as nav (nav.href)}
						{@render item(nav)}
					{/each}
				</Sidebar.Menu>
			</Sidebar.GroupContent>
		</Sidebar.Group>
		<Sidebar.Group class="mt-auto">
			<Sidebar.GroupLabel>System</Sidebar.GroupLabel>
			<Sidebar.GroupContent>
				<Sidebar.Menu>
					{#each systemNav as nav (nav.href)}
						{@render item(nav)}
					{/each}
				</Sidebar.Menu>
			</Sidebar.GroupContent>
		</Sidebar.Group>
	</Sidebar.Content>
	<Sidebar.Rail />
</Sidebar.Root>
