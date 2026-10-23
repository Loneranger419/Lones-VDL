<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { api, call } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import Logo from '#lib/components/app/logo.svelte';
	import LoaderIcon from '@lucide/svelte/icons/loader-circle';

	const queryClient = useQueryClient();
	const auth = createQuery(() => queries.auth());
	const setup = $derived(auth.data?.setup_required === true);

	let password = $state('');
	let confirm = $state('');
	let remember = $state(true);
	let error = $state('');

	// Only same-site paths, never an absolute URL from the query string.
	const next = $derived.by(() => {
		const value = page.url.searchParams.get('next') ?? '/';
		return value.startsWith('/') && !value.startsWith('//') ? value : '/';
	});

	$effect(() => {
		if (auth.data?.authenticated) goto(next, { replace: true });
	});

	const submit = createMutation(() => ({
		mutationFn: () =>
			setup
				? call(api.POST('/api/auth/setup', { body: { password, remember } }))
				: call(api.POST('/api/auth/login', { body: { password, remember } })),
		onSuccess: async () => {
			await queryClient.invalidateQueries({ queryKey: keys.auth });
		},
		onError: (e) => {
			error = e.message === 'wrong password' ? 'That password is not right.' : e.message;
			password = '';
		}
	}));

	function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		if (setup && password !== confirm) {
			error = 'The passwords do not match.';
			return;
		}
		submit.mutate();
	}
</script>

<svelte:head><title>{setup ? 'Set up' : 'Sign in'} · Lones-VDL</title></svelte:head>

<div class="relative grid min-h-svh place-items-center overflow-hidden bg-background px-4 py-10">
	<!-- soft blue glow behind the card -->
	<div
		class="pointer-events-none absolute top-1/2 left-1/2 size-[42rem] -translate-1/2 rounded-full bg-primary/15 blur-3xl"
	></div>

	<div class="relative w-full max-w-sm">
		<div class="mb-8 flex flex-col items-center gap-3 text-center">
			<Logo class="size-14" />
			<div>
				<h1 class="text-2xl font-semibold tracking-tight">Lones-VDL</h1>
				<p class="text-sm text-muted-foreground">
					{setup ? 'Choose a password to protect your archive.' : 'Sign in to your archive.'}
				</p>
			</div>
		</div>

		{#if auth.data}
			<form {onsubmit} class="space-y-4 rounded-2xl border bg-card/80 p-6 shadow-xl backdrop-blur">
				{#if error}
					<Alert.Root variant="destructive">
						<Alert.Description>{error}</Alert.Description>
					</Alert.Root>
				{/if}
				<div class="space-y-2">
					<Label for="password">{setup ? 'New password' : 'Password'}</Label>
					<Input
						id="password"
						type="password"
						bind:value={password}
						autocomplete={setup ? 'new-password' : 'current-password'}
						minlength={setup ? 8 : undefined}
						required
						autofocus
					/>
					{#if setup}
						<p class="text-xs text-muted-foreground">At least 8 characters.</p>
					{/if}
				</div>
				{#if setup}
					<div class="space-y-2">
						<Label for="confirm">Repeat password</Label>
						<Input
							id="confirm"
							type="password"
							bind:value={confirm}
							autocomplete="new-password"
							required
						/>
					</div>
				{/if}
				<div class="flex items-center gap-2">
					<Checkbox id="remember" bind:checked={remember} />
					<Label for="remember" class="font-normal">Remember this device</Label>
				</div>
				<Button type="submit" class="w-full" disabled={submit.isPending || !password}>
					{#if submit.isPending}<LoaderIcon class="animate-spin" />{/if}
					{setup ? 'Create password' : 'Sign in'}
				</Button>
			</form>
		{/if}
	</div>
</div>
