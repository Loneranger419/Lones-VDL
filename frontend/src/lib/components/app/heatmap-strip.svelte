<!--
	"Most replayed": how often each stretch of the video was replayed, drawn as a thin graph under
	the player with the chapter boundaries and the playhead. Click or drag to seek.
-->
<script lang="ts">
	import type { Schemas } from '#lib/api/client.js';
	import { duration as clock } from '#lib/format.js';

	type Point = Schemas['HeatPointOut'];
	type Chapter = Schemas['ChapterOut'];

	let {
		heatmap,
		chapters = [],
		total,
		position,
		onseek
	}: {
		heatmap: Point[];
		chapters?: Chapter[];
		total: number;
		position: number;
		onseek: (seconds: number) => void;
	} = $props();

	const WIDTH = 1000; // drawing units; the SVG stretches to the available width
	const HEIGHT = 40;

	// Smooth area through the middle of each segment. The tallest stretch reaches the top.
	const area = $derived.by(() => {
		if (!heatmap.length || !total) return '';
		const x = (seconds: number) => (Math.min(seconds, total) / total) * WIDTH;
		const y = (value: number) => HEIGHT - value * (HEIGHT - 4);
		const mids = heatmap.map((p) => ({ x: x((p.start + p.end) / 2), y: y(p.value) }));
		let path = `M 0 ${HEIGHT} L 0 ${mids[0].y}`;
		for (let i = 0; i < mids.length; i++) {
			const here = mids[i];
			const before = mids[i - 1] ?? { x: 0, y: here.y };
			const mid = (before.x + here.x) / 2;
			path += ` C ${mid} ${before.y}, ${mid} ${here.y}, ${here.x} ${here.y}`;
		}
		const last = mids[mids.length - 1];
		return `${path} L ${WIDTH} ${last.y} L ${WIDTH} ${HEIGHT} Z`;
	});

	let hover = $state<{ at: number; fraction: number } | null>(null);
	let dragging = false;
	let box = $state<HTMLDivElement>();

	function secondsAt(event: PointerEvent) {
		const rect = box!.getBoundingClientRect();
		const fraction = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
		return { at: fraction * total, fraction };
	}

	const chapterAt = (seconds: number) =>
		chapters.find((c) => seconds >= c.start && seconds < c.end)?.title;

	function heatAt(seconds: number) {
		const point = heatmap.find((p) => seconds >= p.start && seconds < p.end);
		return point && point.value >= 0.66 ? 'Most replayed' : undefined;
	}

	function onmove(event: PointerEvent) {
		hover = secondsAt(event);
		if (dragging) onseek(hover.at);
	}
	function ondown(event: PointerEvent) {
		dragging = true;
		box?.setPointerCapture(event.pointerId);
		onseek(secondsAt(event).at);
	}
	function onkeydown(event: KeyboardEvent) {
		const step = event.key === 'ArrowRight' ? 5 : event.key === 'ArrowLeft' ? -5 : 0;
		if (step) {
			event.preventDefault();
			onseek(Math.min(Math.max(position + step, 0), total));
		}
	}

	const playhead = $derived(total ? Math.min(position / total, 1) * 100 : 0);
</script>

<div
	bind:this={box}
	class="group relative h-10 w-full cursor-pointer touch-none select-none"
	role="slider"
	tabindex="0"
	aria-label="Most replayed sections; seek"
	aria-valuemin={0}
	aria-valuemax={Math.floor(total)}
	aria-valuenow={Math.floor(position)}
	aria-valuetext={clock(position)}
	onpointermove={onmove}
	onpointerdown={ondown}
	onpointerup={() => (dragging = false)}
	onpointerleave={() => (hover = null)}
	{onkeydown}
>
	<svg
		viewBox="0 0 {WIDTH} {HEIGHT}"
		preserveAspectRatio="none"
		class="absolute inset-0 size-full"
		aria-hidden="true"
	>
		<path d={area} class="fill-primary/25 group-hover:fill-primary/35" />
		{#each chapters.slice(1) as chapter (chapter.start)}
			<line
				x1={(chapter.start / total) * WIDTH}
				x2={(chapter.start / total) * WIDTH}
				y1="0"
				y2={HEIGHT}
				class="stroke-background"
				stroke-width="3"
				vector-effect="non-scaling-stroke"
			/>
		{/each}
	</svg>
	<div class="absolute inset-x-0 bottom-0 h-0.5 bg-border"></div>
	<div class="absolute bottom-0 left-0 h-0.5 bg-primary" style:width="{playhead}%"></div>
	<div class="absolute inset-y-0 w-0.5 bg-primary" style:left="{playhead}%"></div>

	{#if hover}
		<div
			class="absolute inset-y-0 w-px bg-foreground/40"
			style:left="{hover.fraction * 100}%"
		></div>
		<div
			class="pointer-events-none absolute bottom-full z-10 mb-1 -translate-x-1/2 rounded-md bg-popover px-2 py-1 text-center text-xs whitespace-nowrap text-popover-foreground shadow-md ring-1 ring-border"
			style:left="clamp(4rem, {hover.fraction * 100}%, calc(100% - 4rem))"
		>
			{#if chapterAt(hover.at)}<div class="max-w-56 truncate font-medium">
					{chapterAt(hover.at)}
				</div>{/if}
			<div class="text-muted-foreground">
				{clock(hover.at)}{#if heatAt(hover.at)}
					· {heatAt(hover.at)}{/if}
			</div>
		</div>
	{/if}
</div>
