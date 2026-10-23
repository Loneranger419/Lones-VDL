<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { setMode, userPrefersMode } from 'mode-watcher';
	import { toast } from 'svelte-sonner';
	import * as Card from '#lib/components/ui/card/index.js';
	import * as ToggleGroup from '#lib/components/ui/toggle-group/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { api, call, type RuntimeSettings } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { QUALITY_LABELS } from '#lib/format.js';
	import PageHeader from '#lib/components/app/page-header.svelte';
	import SimpleSelect from '#lib/components/app/simple-select.svelte';
	import SunIcon from '@lucide/svelte/icons/sun';
	import MoonIcon from '@lucide/svelte/icons/moon';
	import MonitorIcon from '@lucide/svelte/icons/monitor';
	import LogOutIcon from '@lucide/svelte/icons/log-out';

	const queryClient = useQueryClient();
	const settings = createQuery(() => queries.settings());

	// Local draft of the runtime settings; saved together.
	let draft = $state<RuntimeSettings | null>(null);
	$effect.pre(() => {
		if (settings.data && !draft) draft = { ...settings.data.current };
	});
	const dirty = $derived(
		!!draft &&
			!!settings.data &&
			(Object.keys(draft) as (keyof RuntimeSettings)[]).some(
				(k) => draft![k] !== settings.data!.current[k]
			)
	);

	const save = createMutation(() => ({
		mutationFn: (body: RuntimeSettings) => call(api.PATCH('/api/settings', { body })),
		onSuccess: (saved) => {
			queryClient.setQueryData(keys.settings, saved);
			draft = { ...saved.current };
			queryClient.invalidateQueries({ queryKey: keys.ytdlp });
			toast.success('Settings saved');
		},
		onError: (e) => toast.error(e.message)
	}));

	const qualityOptions = Object.entries(QUALITY_LABELS).map(([value, label]) => ({ value, label }));
	const concurrencyOptions = Array.from({ length: 8 }, (_, i) => ({
		value: String(i + 1),
		label: i === 0 ? '1 at a time' : `${i + 1} at once`
	}));
	const intervalOptions = [
		{ value: '0', label: 'Off' },
		{ value: '1', label: 'Every hour' },
		{ value: '3', label: 'Every 3 hours' },
		{ value: '6', label: 'Every 6 hours' },
		{ value: '12', label: 'Every 12 hours' },
		{ value: '24', label: 'Once a day' },
		{ value: '168', label: 'Once a week' }
	];
	/** Keep a custom value (set via the API or env) selectable instead of hiding it. */
	function withCurrent(options: { value: string; label: string }[], value: number) {
		return options.some((o) => o.value === String(value))
			? options
			: [...options, { value: String(value), label: `Every ${value} hours` }];
	}

	// --- Password --------------------------------------------------------------------------
	let current = $state('');
	let next = $state('');
	let confirm = $state('');
	const mismatch = $derived(confirm.length > 0 && next !== confirm);

	const changePassword = createMutation(() => ({
		mutationFn: () =>
			call(
				api.POST('/api/auth/password', {
					body: { current_password: current, new_password: next }
				})
			),
		onSuccess: () => {
			current = next = confirm = '';
			toast.success('Password changed', {
				description: 'Other signed-in devices were signed out.'
			});
		},
		onError: (e) => toast.error(e.message)
	}));

	async function logout() {
		await call(api.POST('/api/auth/logout'));
		queryClient.clear();
		queryClient.setQueryData(keys.auth, { setup_required: false, authenticated: false });
	}
</script>

<PageHeader title="Settings" />

<div class="max-w-3xl space-y-6">
	<Card.Root>
		<Card.Header>
			<Card.Title>Appearance</Card.Title>
			<Card.Description>Saved in this browser.</Card.Description>
		</Card.Header>
		<Card.Content>
			<ToggleGroup.Root
				type="single"
				variant="outline"
				value={userPrefersMode.current}
				onValueChange={(v) => v && setMode(v as 'dark' | 'light' | 'system')}
			>
				<ToggleGroup.Item value="dark" class="gap-2 px-4"><MoonIcon /> Dark</ToggleGroup.Item>
				<ToggleGroup.Item value="light" class="gap-2 px-4"><SunIcon /> Light</ToggleGroup.Item>
				<ToggleGroup.Item value="system" class="gap-2 px-4"><MonitorIcon /> System</ToggleGroup.Item
				>
			</ToggleGroup.Root>
		</Card.Content>
	</Card.Root>

	<Card.Root>
		<Card.Header>
			<Card.Title>Downloads</Card.Title>
			<Card.Description>Apply to the whole archive and take effect immediately.</Card.Description>
		</Card.Header>
		<Card.Content>
			{#if !draft}
				<Skeleton class="h-48 w-full" />
			{:else}
				<form
					class="grid gap-5 sm:grid-cols-2"
					onsubmit={(e) => {
						e.preventDefault();
						if (draft) save.mutate(draft);
					}}
				>
					<div class="space-y-2">
						<Label>Default quality</Label>
						<SimpleSelect
							class="w-full"
							label="Default quality"
							options={qualityOptions}
							bind:value={draft.default_quality}
						/>
						<p class="text-xs text-muted-foreground">Best keeps the original AV1/VP9 streams.</p>
					</div>
					<div class="space-y-2">
						<Label>Simultaneous downloads</Label>
						<SimpleSelect
							class="w-full"
							label="Simultaneous downloads"
							options={concurrencyOptions}
							value={String(draft.download_concurrency)}
							onchange={(v) => draft && (draft.download_concurrency = Number(v))}
						/>
						<p class="text-xs text-muted-foreground">
							More than 2 makes YouTube throttling likelier.
						</p>
					</div>
					<div class="space-y-2">
						<Label>Check auto-archived channels</Label>
						<SimpleSelect
							class="w-full"
							label="Channel check interval"
							options={withCurrent(intervalOptions, draft.channel_watch_interval_hours)}
							value={String(draft.channel_watch_interval_hours)}
							onchange={(v) => draft && (draft.channel_watch_interval_hours = Number(v))}
						/>
					</div>
					<div class="space-y-2">
						<Label>Update yt-dlp</Label>
						<SimpleSelect
							class="w-full"
							label="yt-dlp update interval"
							options={withCurrent(intervalOptions, draft.ytdlp_update_interval_hours)}
							value={String(draft.ytdlp_update_interval_hours)}
							onchange={(v) => draft && (draft.ytdlp_update_interval_hours = Number(v))}
						/>
					</div>
					<div class="space-y-2 sm:col-span-2">
						<Label>yt-dlp release channel</Label>
						<ToggleGroup.Root
							type="single"
							variant="outline"
							size="sm"
							value={draft.ytdlp_channel}
							onValueChange={(v) => v && draft && (draft.ytdlp_channel = v as 'stable' | 'nightly')}
						>
							<ToggleGroup.Item value="stable" class="px-4">Stable</ToggleGroup.Item>
							<ToggleGroup.Item value="nightly" class="px-4">Nightly</ToggleGroup.Item>
						</ToggleGroup.Root>
						<p class="text-xs text-muted-foreground">
							Nightly gets YouTube fixes days earlier; switch to it if downloads suddenly break.
						</p>
					</div>
					<div class="flex gap-2 sm:col-span-2">
						<Button type="submit" disabled={!dirty || save.isPending}>Save changes</Button>
						{#if dirty}
							<Button
								variant="ghost"
								onclick={() => settings.data && (draft = { ...settings.data.current })}
							>
								Discard
							</Button>
						{/if}
					</div>
				</form>
			{/if}
		</Card.Content>
	</Card.Root>

	<Card.Root>
		<Card.Header>
			<Card.Title>Password</Card.Title>
			<Card.Description>Changing it signs out every other device.</Card.Description>
		</Card.Header>
		<Card.Content>
			<form
				class="grid max-w-sm gap-4"
				onsubmit={(e) => {
					e.preventDefault();
					if (!mismatch) changePassword.mutate();
				}}
			>
				<input
					type="text"
					name="username"
					value="admin"
					autocomplete="username"
					class="hidden"
					readonly
				/>
				<div class="space-y-2">
					<Label for="current-password">Current password</Label>
					<Input
						id="current-password"
						type="password"
						bind:value={current}
						autocomplete="current-password"
						required
					/>
				</div>
				<div class="space-y-2">
					<Label for="new-password">New password</Label>
					<Input
						id="new-password"
						type="password"
						bind:value={next}
						autocomplete="new-password"
						minlength={8}
						required
					/>
				</div>
				<div class="space-y-2">
					<Label for="confirm-password">Confirm new password</Label>
					<Input
						id="confirm-password"
						type="password"
						bind:value={confirm}
						autocomplete="new-password"
						aria-invalid={mismatch}
						required
					/>
					{#if mismatch}<p class="text-xs text-brand-red">The passwords don’t match.</p>{/if}
				</div>
				<div>
					<Button
						type="submit"
						disabled={!current || next.length < 8 || mismatch || changePassword.isPending}
					>
						Change password
					</Button>
				</div>
			</form>
		</Card.Content>
	</Card.Root>

	<Card.Root>
		<Card.Header>
			<Card.Title>This device</Card.Title>
		</Card.Header>
		<Card.Content>
			<Button variant="outline" onclick={logout}><LogOutIcon /> Sign out</Button>
		</Card.Content>
	</Card.Root>
</div>
