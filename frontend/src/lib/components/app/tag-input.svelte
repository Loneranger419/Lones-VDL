<!--
	A list of tags the user builds by typing. Suggestions (most used first, with how many videos
	carry each) come from the archive; free text is accepted too, so a tag can be hidden before
	any video has it.
-->
<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { queries } from '#lib/api/queries.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import XIcon from '@lucide/svelte/icons/x';

	let {
		tags = $bindable([]),
		label,
		placeholder = 'Type a tag, press Enter',
		onchange,
		class: className = ''
	}: {
		tags?: string[];
		label: string;
		placeholder?: string;
		onchange?: (tags: string[]) => void;
		class?: string;
	} = $props();

	const uid = $props.id();
	const listId = `tags-${uid}`;
	let text = $state('');
	const suggestions = createQuery(() => queries.tags(text.trim()));

	const norm = (value: string) => value.toLowerCase().split(/\s+/).filter(Boolean).join(' ');

	function set(next: string[]) {
		tags = next;
		onchange?.(next);
	}

	function add() {
		const tag = norm(text);
		text = '';
		if (tag && !tags.map(norm).includes(tag)) set([...tags, tag]);
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ',') {
			event.preventDefault();
			add();
		} else if (event.key === 'Backspace' && !text && tags.length) {
			set(tags.slice(0, -1));
		}
	}

	// Picking a suggestion from the list fills the box; add it right away.
	function oninput(event: Event) {
		const picked = (event as InputEvent).inputType === 'insertReplacementText';
		if (picked || !(event as InputEvent).inputType) add();
	}
</script>

<div
	class={[
		'flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border bg-transparent px-2 py-1.5 focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50',
		className
	]}
>
	{#each tags as tag (tag)}
		<Badge variant="secondary" class="gap-1 pr-1">
			{tag}
			<button
				type="button"
				class="rounded-full p-0.5 hover:bg-foreground/10"
				aria-label="Remove {tag}"
				onclick={() => set(tags.filter((t) => t !== tag))}
			>
				<XIcon class="size-3" />
			</button>
		</Badge>
	{/each}
	<input
		type="text"
		list={listId}
		class="min-w-32 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
		aria-label={label}
		{placeholder}
		autocomplete="off"
		bind:value={text}
		{onkeydown}
		{oninput}
		onblur={add}
	/>
	<datalist id={listId}>
		{#each suggestions.data ?? [] as s (s.tag)}
			<option value={s.label}>{s.videos} {s.videos === 1 ? 'video' : 'videos'}</option>
		{/each}
	</datalist>
</div>
