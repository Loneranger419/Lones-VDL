<script lang="ts">
	import { page } from '$app/state';
	import { createQuery } from '@tanstack/svelte-query';
	import { queries } from '#lib/api/queries.js';
	import { cookieProblem } from '#lib/cookies.js';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';

	const cookies = createQuery(() => queries.cookies());
	const problem = $derived(cookieProblem(cookies.data));
</script>

{#if problem && page.url.pathname !== '/health'}
	<div
		role="alert"
		class={[
			'flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2 text-sm',
			problem.level === 'error'
				? 'border-brand-red/30 bg-brand-red/10 text-foreground'
				: 'border-warning/30 bg-warning/10 text-foreground'
		]}
	>
		<TriangleAlertIcon
			class={['size-4 shrink-0', problem.level === 'error' ? 'text-brand-red' : 'text-warning']}
		/>
		<span class="flex-1">{problem.message}</span>
		<a href="/health#cookies" class="font-medium text-primary underline-offset-4 hover:underline">
			Fix cookies
		</a>
	</div>
{/if}
