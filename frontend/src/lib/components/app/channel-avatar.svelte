<script lang="ts">
	import { mediaUrl, type ChannelBrief } from '#lib/api/client.js';
	import { cn } from '#lib/utils.js';

	let { channel, class: className = '' }: { channel: ChannelBrief; class?: string } = $props();

	const initials = $derived(
		(channel.name ?? channel.handle ?? '?')
			.replace(/^@/, '')
			.split(/\s+/)
			.slice(0, 2)
			.map((w) => w[0]?.toUpperCase() ?? '')
			.join('')
	);
	let failed = $state(false);
</script>

<span
	class={cn(
		'relative inline-grid size-9 shrink-0 place-items-center overflow-hidden rounded-full bg-gradient-to-br from-primary/70 to-primary text-xs font-semibold text-primary-foreground',
		className
	)}
>
	{#if channel.has_avatar && !failed}
		<img
			src={mediaUrl.avatar(channel.id)}
			alt=""
			loading="lazy"
			class="size-full object-cover"
			onerror={() => (failed = true)}
		/>
	{:else}
		{initials}
	{/if}
</span>
