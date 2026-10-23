<script lang="ts">
	import type { Component, Snippet } from 'svelte';

	let {
		icon: Icon,
		title,
		description,
		children
	}: { icon?: Component; title: string; description?: string; children?: Snippet } = $props();
</script>

<div
	class="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed px-6 py-14 text-center"
>
	{#if Icon}
		<div class="grid size-12 place-items-center rounded-full bg-primary/10 text-primary">
			<Icon class="size-6" />
		</div>
	{/if}
	<div class="space-y-1">
		<h2 class="font-semibold">{title}</h2>
		{#if description}<p class="max-w-md text-sm text-muted-foreground">{description}</p>{/if}
	</div>
	{@render children?.()}
</div>
