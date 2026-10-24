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
	import FilterPresets from '#lib/components/app/filter-presets.svelte';
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
					<fieldset class="space-y-5 rounded-xl border p-4 sm:col-span-2">
						<legend class="px-2 text-sm font-medium">YouTube download limits</legend>
						<p class="text-sm text-muted-foreground">
							Each site has its own limits. Downloads run one at a time, and shorts wait while a
							video or stream can run. These reduce how much YouTube sees from this server; they are
							starting points, not guarantees against rate limits or account restrictions.
						</p>
						<div class="grid gap-5 sm:grid-cols-2">
							<div class="space-y-2">
								<Label for="daily-cap">Videos per day</Label>
								<Input
									id="daily-cap"
									type="number"
									min="1"
									step="1"
									bind:value={draft.daily_download_cap}
								/>
								<p class="text-xs text-muted-foreground">
									Videos and streams, over any rolling 24 hours. The queue resumes by itself when
									the limit frees up.
								</p>
							</div>
							<div class="space-y-2">
								<Label for="daily-auth-cap">Videos per day using an account</Label>
								<Input
									id="daily-auth-cap"
									type="number"
									min="0"
									step="1"
									bind:value={draft.daily_auth_cap}
								/>
								<p class="text-xs text-muted-foreground">
									Counted within the limit above. 0 downloads anonymously only.
								</p>
							</div>
							<div class="space-y-2">
								<Label for="shorts-cap">Shorts per day</Label>
								<Input
									id="shorts-cap"
									type="number"
									min="1"
									step="1"
									bind:value={draft.shorts_daily_cap}
								/>
								<p class="text-xs text-muted-foreground">
									Separate from videos, so a shorts backfill never uses up the video limit.
								</p>
							</div>
							<div class="space-y-2">
								<Label for="shorts-auth-cap">Shorts per day using an account</Label>
								<Input
									id="shorts-auth-cap"
									type="number"
									min="0"
									step="1"
									bind:value={draft.shorts_daily_auth_cap}
								/>
								<p class="text-xs text-muted-foreground">
									Counted within the shorts limit. Shorts rarely need an account.
								</p>
							</div>
							<div class="space-y-2 sm:col-span-2">
								<Label for="delay-min">Pause between downloads (seconds)</Label>
								<div class="flex items-center gap-2">
									<Input
										id="delay-min"
										class="w-24"
										type="number"
										min="15"
										max="30"
										step="1"
										aria-label="Shortest pause in seconds"
										bind:value={draft.video_delay_min_seconds}
									/>
									<span class="text-sm text-muted-foreground">to</span>
									<Input
										class="w-24"
										type="number"
										min="15"
										max="30"
										step="1"
										aria-label="Longest pause in seconds"
										bind:value={draft.video_delay_max_seconds}
									/>
								</div>
								<p class="text-xs text-muted-foreground">
									A random pause in this range (15 to 30) follows every download.
								</p>
							</div>
						</div>
					</fieldset>
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
			<Card.Title>Library filters</Card.Title>
			<Card.Description>
				Saved tag filters. The default one applies on Home, Library, and channel pages; you can
				switch it off from the page. Search, collections, and Up next are never filtered.
			</Card.Description>
		</Card.Header>
		<Card.Content>
			<FilterPresets />
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
