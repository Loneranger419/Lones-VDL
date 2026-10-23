<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Card from '#lib/components/ui/card/index.js';

	// Phase 1 placeholder: proves the build, the API proxy, and the component library work.
	type Health = { status: string; version: string };

	let health = $state<Health | null>(null);
	let error = $state('');

	async function check() {
		error = '';
		try {
			const response = await fetch('/api/health');
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			health = await response.json();
		} catch (e) {
			health = null;
			error = e instanceof Error ? e.message : String(e);
		}
	}

	$effect(() => {
		check();
	});
</script>

<svelte:head>
	<title>Lones-VDL</title>
</svelte:head>

<main class="grid min-h-dvh place-items-center p-4">
	<Card.Root class="w-full max-w-sm">
		<Card.Header>
			<Card.Title>Lones-VDL v2</Card.Title>
			<Card.Description>Skeleton build. The real UI arrives in Phase 4.</Card.Description>
		</Card.Header>
		<Card.Content>
			{#if health}
				<p>API: <strong>{health.status}</strong> · v{health.version}</p>
			{:else if error}
				<p class="text-destructive">API unreachable: {error}</p>
			{:else}
				<p class="text-muted-foreground">Checking API…</p>
			{/if}
		</Card.Content>
		<Card.Footer>
			<Button onclick={check}>Check again</Button>
		</Card.Footer>
	</Card.Root>
</main>
