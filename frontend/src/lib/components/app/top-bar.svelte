<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useQueryClient } from '@tanstack/svelte-query';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { api, call } from '#lib/api/client.js';
	import { keys } from '#lib/api/queries.js';
	import { live } from '#lib/api/events.svelte.js';
	import { ui } from '#lib/ui-state.svelte.js';
	import ThemeToggle from './theme-toggle.svelte';
	import Logo from './logo.svelte';
	import SearchIcon from '@lucide/svelte/icons/search';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import UserIcon from '@lucide/svelte/icons/circle-user-round';
	import LogOutIcon from '@lucide/svelte/icons/log-out';
	import SettingsIcon from '@lucide/svelte/icons/settings';

	const queryClient = useQueryClient();
	const urlQuery = $derived(
		page.url.pathname === '/library' ? (page.url.searchParams.get('q') ?? '') : ''
	);
	let query = $state('');
	// Follow the URL (back button, "clear search"), but let the user type freely in between.
	$effect.pre(() => {
		query = urlQuery;
	});

	function search(event: SubmitEvent) {
		event.preventDefault();
		const params = new URLSearchParams(page.url.pathname === '/library' ? page.url.search : '');
		if (query.trim()) params.set('q', query.trim());
		else params.delete('q');
		goto(`/library${params.size ? `?${params}` : ''}`);
	}

	async function logout() {
		await call(api.POST('/api/auth/logout'));
		queryClient.clear();
		queryClient.setQueryData(keys.auth, { setup_required: false, authenticated: false });
	}
</script>

<header
	class="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur-lg md:px-4"
>
	<Sidebar.Trigger class="hidden md:inline-flex" />
	<a href="/" class="md:hidden" aria-label="Home"><Logo class="size-7" /></a>

	<form onsubmit={search} class="relative mx-auto w-full max-w-xl" role="search">
		<SearchIcon
			class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
		/>
		<input
			bind:value={query}
			type="search"
			placeholder="Search your archive"
			aria-label="Search your archive"
			class="h-9 w-full rounded-full border border-input bg-muted/50 pr-4 pl-9 text-sm transition-colors outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-background focus:ring-3 focus:ring-ring/30"
		/>
	</form>

	<div class="flex items-center gap-1">
		{#if !live.connected}
			<span
				class="hidden text-xs text-muted-foreground sm:inline"
				title="Live updates are reconnecting"
			>
				Reconnecting…
			</span>
		{/if}
		<Button onclick={() => ui.openAdd()} size="sm" class="gap-1.5 rounded-full px-3">
			<PlusIcon />
			<span class="hidden sm:inline">Add</span>
		</Button>
		<ThemeToggle />
		<DropdownMenu.Root>
			<DropdownMenu.Trigger>
				{#snippet child({ props })}
					<Button {...props} variant="ghost" size="icon" aria-label="Account">
						<UserIcon />
					</Button>
				{/snippet}
			</DropdownMenu.Trigger>
			<DropdownMenu.Content align="end">
				<DropdownMenu.Item onclick={() => goto('/settings')}>
					<SettingsIcon /> Settings
				</DropdownMenu.Item>
				<DropdownMenu.Separator />
				<DropdownMenu.Item onclick={logout}>
					<LogOutIcon /> Sign out
				</DropdownMenu.Item>
			</DropdownMenu.Content>
		</DropdownMenu.Root>
	</div>
</header>
