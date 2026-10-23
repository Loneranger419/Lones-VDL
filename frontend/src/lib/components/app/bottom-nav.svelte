<script lang="ts">
	import { page } from '$app/state';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import { isActive, mainNav, systemNav } from '#lib/nav.js';
	import MenuIcon from '@lucide/svelte/icons/menu';

	const sidebar = Sidebar.useSidebar();
	const items = mainNav.filter((n) => n.mobile);
	// "More" is lit when the current page is one only reachable through it.
	const moreActive = $derived(
		[...mainNav.filter((n) => !n.mobile), ...systemNav].some((n) => isActive(page.url.pathname, n))
	);
</script>

<!-- Phones only: thumb-reachable navigation. The full menu opens as a sheet via "More". -->
<nav
	class="fixed inset-x-0 bottom-0 z-40 border-t bg-background/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-lg md:hidden"
	aria-label="Main"
>
	<ul class="mx-auto grid h-15 max-w-lg grid-cols-5">
		{#each items as nav (nav.href)}
			{@const active = isActive(page.url.pathname, nav)}
			<li>
				<a
					href={nav.href}
					class={[
						'flex h-full flex-col items-center justify-center gap-0.5 text-[0.7rem] font-medium transition-colors',
						active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
					]}
					aria-current={active ? 'page' : undefined}
				>
					<nav.icon class="size-5" strokeWidth={active ? 2.4 : 2} />
					{nav.label}
				</a>
			</li>
		{/each}
		<li>
			<button
				type="button"
				onclick={() => sidebar.setOpenMobile(true)}
				class={[
					'flex h-full w-full flex-col items-center justify-center gap-0.5 text-[0.7rem] font-medium transition-colors',
					moreActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
				]}
			>
				<MenuIcon class="size-5" />
				More
			</button>
		</li>
	</ul>
</nav>
