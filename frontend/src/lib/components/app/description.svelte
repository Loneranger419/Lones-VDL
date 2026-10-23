<!-- Video description as plain text with clickable links and timestamps (no HTML is rendered). -->
<script lang="ts">
	let { text, onseek }: { text: string; onseek?: (seconds: number) => void } = $props();

	type Part = { kind: 'text' | 'link' | 'time'; value: string; seconds?: number };

	const TOKEN = /(https?:\/\/[^\s<>"]+)|(?<![\w:])((?:\d{1,2}:)?\d{1,2}:\d{2})(?![\w:])/g;

	function toSeconds(stamp: string) {
		return stamp.split(':').reduce((total, part) => total * 60 + Number(part), 0);
	}

	const parts = $derived.by(() => {
		const out: Part[] = [];
		let last = 0;
		for (const match of text.matchAll(TOKEN)) {
			const index = match.index ?? 0;
			if (index > last) out.push({ kind: 'text', value: text.slice(last, index) });
			if (match[1]) {
				// Trailing punctuation usually belongs to the sentence, not the URL.
				const url = match[1].replace(/[).,!?;:'\]]+$/, '');
				out.push({ kind: 'link', value: url });
				last = index + url.length;
				continue;
			}
			out.push({ kind: 'time', value: match[2], seconds: toSeconds(match[2]) });
			last = index + match[0].length;
		}
		if (last < text.length) out.push({ kind: 'text', value: text.slice(last) });
		return out;
	});
</script>

<p class="text-sm leading-relaxed break-words whitespace-pre-wrap">
	{#each parts as part, i (i)}
		{#if part.kind === 'link'}
			<a
				href={part.value}
				target="_blank"
				rel="noopener noreferrer"
				class="text-primary hover:underline">{part.value}</a
			>
		{:else if part.kind === 'time' && onseek}
			<button
				type="button"
				class="text-primary hover:underline"
				onclick={() => onseek(part.seconds ?? 0)}>{part.value}</button
			>
		{:else}
			{part.value}
		{/if}
	{/each}
</p>
