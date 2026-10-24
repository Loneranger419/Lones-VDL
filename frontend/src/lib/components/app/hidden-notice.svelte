<!-- Says how many matches a tag preset is hiding, with one click to show them. -->
<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import EyeOffIcon from '@lucide/svelte/icons/eye-off';

	let { hidden, preset, onshow }: { hidden: number; preset: string; onshow: () => void } = $props();
</script>

{#if hidden > 0}
	<p class="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
		<EyeOffIcon class="size-4" />
		{hidden.toLocaleString()}
		{hidden === 1 ? 'video' : 'videos'} hidden by “{preset}”.
		<Button variant="link" size="sm" class="h-auto p-0" onclick={onshow}>Show them</Button>
	</p>
{/if}
