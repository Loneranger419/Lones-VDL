<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import { setUnauthorizedHandler } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { connectEvents } from '#lib/api/events.svelte.js';
	import AppSidebar from '#lib/components/app/app-sidebar.svelte';
	import BottomNav from '#lib/components/app/bottom-nav.svelte';
	import TopBar from '#lib/components/app/top-bar.svelte';
	import CookieBanner from '#lib/components/app/cookie-banner.svelte';
	import AddDownloadDialog from '#lib/components/app/add-download-dialog.svelte';
	import Logo from '#lib/components/app/logo.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const queryClient = useQueryClient();
	const auth = createQuery(() => queries.auth());
	const authenticated = $derived(auth.data?.authenticated === true);

	setUnauthorizedHandler(() =>
		queryClient.setQueryData(keys.auth, { setup_required: false, authenticated: false })
	);

	$effect(() => {
		if (auth.data && !auth.data.authenticated) {
			const next = page.url.pathname + page.url.search;
			goto(next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`, {
				replace: true
			});
		}
	});

	$effect(() => {
		if (authenticated) return connectEvents(queryClient);
	});
</script>

{#if authenticated}
	<Sidebar.Provider>
		<AppSidebar />
		<Sidebar.Inset class="min-w-0">
			<TopBar />
			<CookieBanner />
			<main class="flex-1 px-4 pt-5 pb-[calc(var(--bottom-nav-height)+1.5rem)] md:px-6 md:pb-10">
				{@render children()}
			</main>
		</Sidebar.Inset>
		<BottomNav />
	</Sidebar.Provider>
	<AddDownloadDialog />
{:else}
	<div class="grid min-h-svh place-items-center">
		<Logo class="size-12 animate-pulse" />
	</div>
{/if}
