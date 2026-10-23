<script lang="ts">
	import { cn } from '#lib/utils.js';

	let { class: className = '' }: { class?: string } = $props();
</script>

<!-- Archive box with a play mark; the red dot is the "recording" accent. -->
<svg viewBox="0 0 32 32" class={cn('size-8 shrink-0', className)} aria-hidden="true">
	<defs>
		<linearGradient id="lvdl-logo" x1="0" y1="0" x2="1" y2="1">
			<stop offset="0" stop-color="oklch(0.66 0.18 250)" />
			<stop offset="1" stop-color="oklch(0.5 0.21 264)" />
		</linearGradient>
	</defs>
	<rect x="1" y="1" width="30" height="30" rx="8" fill="url(#lvdl-logo)" />
	<path
		d="M12.5 10.2v11.6a.8.8 0 0 0 1.2.7l9.4-5.8a.8.8 0 0 0 0-1.4l-9.4-5.8a.8.8 0 0 0-1.2.7Z"
		fill="white"
	/>
	<circle cx="25" cy="7" r="3.2" fill="oklch(0.64 0.22 25)" stroke="white" stroke-width="1.4" />
</svg>
