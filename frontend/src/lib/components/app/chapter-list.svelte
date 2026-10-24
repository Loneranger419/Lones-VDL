<!--
	The video's chapters: the current one on a single line, expandable to the whole list. Choosing
	a chapter seeks there.
-->
<script lang="ts">
	import type { Schemas } from '#lib/api/client.js';
	import { duration as clock } from '#lib/format.js';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';

	type Chapter = Schemas['ChapterOut'];

	let {
		chapters,
		position,
		onseek
	}: { chapters: Chapter[]; position: number; onseek: (seconds: number) => void } = $props();

	let open = $state(false);

	const index = $derived(
		Math.max(
			chapters.findIndex((c) => position >= c.start && position < c.end),
			0
		)
	);
	const current = $derived(chapters[index]);
</script>

<div class="rounded-xl border bg-card">
	<button
		type="button"
		class="flex w-full items-center gap-3 px-3 py-2.5 text-left"
		aria-expanded={open}
		onclick={() => (open = !open)}
	>
		<span class="min-w-0 flex-1">
			<span class="block text-xs text-muted-foreground">
				Chapter {index + 1} of {chapters.length}
			</span>
			<span class="block truncate text-sm font-medium">{current?.title}</span>
		</span>
		<ChevronDownIcon class={['size-4 shrink-0 transition-transform', open && 'rotate-180']} />
	</button>
	{#if open}
		<ol class="max-h-72 divide-y overflow-y-auto border-t">
			{#each chapters as chapter, i (chapter.start)}
				<li>
					<button
						type="button"
						class={[
							'flex w-full items-baseline gap-3 px-3 py-2 text-left text-sm hover:bg-muted/60',
							i === index && 'bg-muted/60 font-medium'
						]}
						onclick={() => onseek(chapter.start)}
					>
						<span class="w-14 shrink-0 text-xs text-primary tabular-nums"
							>{clock(chapter.start)}</span
						>
						<span class="min-w-0 flex-1 truncate">{chapter.title}</span>
					</button>
				</li>
			{/each}
		</ol>
	{/if}
</div>
