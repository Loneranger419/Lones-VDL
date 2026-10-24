<!--
	One YouTube account: import, test, and remove its cookies. The server filters an upload to
	allowed domains and never sends cookie values back; this card only ever sees names and dates.
-->
<script lang="ts">
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Switch } from '#lib/components/ui/switch/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';
	import { api, call, type Account, type Schemas } from '#lib/api/client.js';
	import { keys } from '#lib/api/queries.js';
	import { ROLE_LABELS } from '#lib/accounts.js';
	import { ago, calendarDate } from '#lib/format.js';
	import ConfirmDialog from './confirm-dialog.svelte';
	import UploadIcon from '@lucide/svelte/icons/upload';
	import FlaskIcon from '@lucide/svelte/icons/flask-conical';
	import TrashIcon from '@lucide/svelte/icons/trash-2';
	import LoaderIcon from '@lucide/svelte/icons/loader-circle';

	let { account }: { account: Account } = $props();

	const queryClient = useQueryClient();
	const path = $derived({ params: { path: { account_id: account.id } } });
	const status = $derived(account.status);

	let pasted = $state('');
	let showPaste = $state(false);
	let dragging = $state(false);
	let fileInput = $state<HTMLInputElement>();
	let lastImport = $state<Schemas['AccountImportOut'] | null>(null);
	let confirmCookies = $state(false);
	let confirmAccount = $state(false);

	const refresh = () => {
		queryClient.invalidateQueries({ queryKey: keys.accounts });
		queryClient.invalidateQueries({ queryKey: keys.jobs });
		queryClient.invalidateQueries({ queryKey: keys.policy });
	};

	const upload = createMutation(() => ({
		mutationFn: (text: string) =>
			call(
				api.POST('/api/accounts/{account_id}/cookies', {
					...path,
					body: text,
					bodySerializer: (body: string) => body,
					headers: { 'Content-Type': 'text/plain' }
				})
			),
		onSuccess: (result) => {
			lastImport = result;
			pasted = '';
			showPaste = false;
			refresh();
			toast.success('Cookies saved', {
				description: result.requeued_jobs
					? `${result.requeued_jobs} failed jobs will be retried. Testing the cookies now…`
					: 'Testing them now…'
			});
			test.mutate();
		},
		onError: (e) => toast.error(e.message)
	}));

	const test = createMutation(() => ({
		mutationFn: () => call(api.POST('/api/accounts/{account_id}/test', path)),
		onSuccess: (health) => {
			refresh();
			if (health.status === 'ok') toast.success('YouTube accepted the cookies');
			else toast.error('Cookie test failed', { description: health.detail ?? health.status });
		},
		onError: (e) => toast.error(e.message)
	}));

	const setEnabled = createMutation(() => ({
		mutationFn: (enabled: boolean) =>
			call(api.PATCH('/api/accounts/{account_id}', { ...path, body: { enabled } })),
		onSuccess: refresh,
		onError: (e) => toast.error(e.message)
	}));

	const removeCookies = createMutation(() => ({
		mutationFn: () => call(api.DELETE('/api/accounts/{account_id}/cookies', path)),
		onSuccess: () => {
			lastImport = null;
			refresh();
			toast.success('Cookies removed');
		},
		onError: (e) => toast.error(e.message)
	}));

	const removeAccount = createMutation(() => ({
		mutationFn: () => call(api.DELETE('/api/accounts/{account_id}', path)),
		onSuccess: () => {
			refresh();
			toast.success(`Removed “${account.label}”`);
		},
		onError: (e) => toast.error(e.message)
	}));

	async function importFile(file: File | undefined) {
		if (!file) return;
		if (file.size > 1_000_000) {
			toast.error('That file is too large to be a cookies.txt export.');
			return;
		}
		upload.mutate(await file.text());
	}

	function ondrop(event: DragEvent) {
		event.preventDefault();
		dragging = false;
		importFile(event.dataTransfer?.files[0]);
	}

	const HEALTH: Record<string, { label: string; tone: string }> = {
		ok: { label: 'Working', tone: 'bg-success/15 text-success' },
		invalid: { label: 'Rejected', tone: 'bg-brand-red/15 text-brand-red' },
		error: { label: 'Test failed', tone: 'bg-warning/15 text-warning' },
		untested: { label: 'Not tested', tone: 'bg-muted text-muted-foreground' },
		missing: { label: 'No cookies', tone: 'bg-muted text-muted-foreground' }
	};
	const health = $derived(
		status.present
			? (HEALTH[status.health?.status ?? 'untested'] ?? HEALTH.untested)
			: HEALTH.missing
	);
	const loginNames = $derived(Object.keys(status.login_cookies ?? {}).sort());
	const busy = $derived(
		upload.isPending || test.isPending || removeCookies.isPending || removeAccount.isPending
	);
	const summary = $derived(
		lastImport?.summary as
			| { kept?: number; dropped_domain?: number; dropped_expired?: number; warnings?: string[] }
			| undefined
	);
</script>

<div class={['space-y-4 rounded-xl border p-4', !account.enabled && 'opacity-70']}>
	<div class="flex flex-wrap items-center gap-2">
		<h3 class="font-medium">{account.label}</h3>
		<Badge variant={account.role === 'personal' ? 'outline' : 'secondary'}>
			{ROLE_LABELS[account.role]}
		</Badge>
		<span class={['rounded-full px-2 py-0.5 text-xs font-medium', health.tone]}>
			{health.label}
		</span>
		<label class="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
			Enabled
			<Switch
				checked={account.enabled}
				onCheckedChange={(v) => setEnabled.mutate(v)}
				aria-label="Use this account"
			/>
		</label>
	</div>

	<p class="text-sm text-muted-foreground">
		{#if account.role === 'alternate'}
			Tried when YouTube refuses a download without signing in, such as age-restricted videos or a
			bot check.
		{:else}
			Never used on its own. A video that needs it, such as a members-only one, waits on the
			Downloads page until you approve it.
		{/if}
	</p>

	{#if status.present}
		<dl class="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
			<div>
				<dt class="text-muted-foreground">Saved</dt>
				<dd>{ago(status.updated_at)} · {status.cookie_count} cookies</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">Sign-in expires</dt>
				<dd>
					{status.login_expires
						? calendarDate(status.login_expires.slice(0, 10))
						: 'With the browser session'}
				</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">Last test</dt>
				<dd>
					{#if status.health && status.health.status !== 'untested'}
						{ago(status.health.checked_at)}{status.health.detail
							? ` · ${status.health.detail}`
							: ''}
					{:else}
						Not tested yet
					{/if}
				</dd>
			</div>
			<div>
				<dt class="text-muted-foreground">Sign-in cookies</dt>
				<dd class="flex flex-wrap gap-1">
					{#each loginNames as name (name)}<Badge
							variant="secondary"
							class="font-mono text-[0.7rem]">{name}</Badge
						>{:else}
						<span class="text-brand-red">none found</span>{/each}
				</dd>
			</div>
		</dl>
	{/if}

	<!-- svelte-ignore a11y_no_static_element_interactions (the button inside is the accessible control) -->
	<div
		class={[
			'rounded-xl border-2 border-dashed p-5 text-center transition-colors',
			dragging ? 'border-primary bg-primary/5' : 'border-border'
		]}
		ondragover={(e) => {
			e.preventDefault();
			dragging = true;
		}}
		ondragleave={() => (dragging = false)}
		{ondrop}
	>
		<UploadIcon class="mx-auto mb-2 size-5 text-muted-foreground" />
		<p class="text-sm">
			Drop <span class="font-mono">cookies.txt</span> here, or
			<button
				type="button"
				class="font-medium text-primary hover:underline"
				onclick={() => fileInput?.click()}
			>
				choose a file
			</button>
			·
			<button
				type="button"
				class="font-medium text-primary hover:underline"
				onclick={() => (showPaste = !showPaste)}
			>
				paste it
			</button>
		</p>
		<p class="mt-1 text-xs text-muted-foreground">
			Only YouTube cookies are kept; everything else in the file is discarded.
		</p>
		<input
			bind:this={fileInput}
			type="file"
			accept=".txt,text/plain"
			class="hidden"
			onchange={(e) => importFile(e.currentTarget.files?.[0])}
		/>
	</div>

	{#if showPaste}
		<div class="space-y-2">
			<Textarea
				bind:value={pasted}
				rows={5}
				placeholder="# Netscape HTTP Cookie File"
				class="font-mono text-xs"
				spellcheck={false}
				autocomplete="off"
			/>
			<Button onclick={() => upload.mutate(pasted)} disabled={!pasted.trim() || busy}
				>Save cookies</Button
			>
		</div>
	{/if}

	{#if summary}
		<p class="text-sm text-muted-foreground">
			Kept {summary.kept ?? 0} YouTube cookies; discarded {summary.dropped_domain ?? 0} from other sites{summary.dropped_expired
				? ` and ${summary.dropped_expired} expired`
				: ''}.
		</p>
		{#each summary.warnings ?? [] as warning (warning)}
			<p class="text-sm text-warning">{warning}</p>
		{/each}
	{/if}

	<div class="flex flex-wrap gap-2">
		<Button variant="outline" onclick={() => test.mutate()} disabled={!status.present || busy}>
			{#if test.isPending}<LoaderIcon class="animate-spin" />{:else}<FlaskIcon />{/if}
			Test
		</Button>
		{#if status.present}
			<Button variant="ghost" onclick={() => (confirmCookies = true)} disabled={busy}>
				<TrashIcon /> Remove cookies
			</Button>
		{/if}
		<Button
			variant="ghost"
			class="ml-auto text-muted-foreground"
			onclick={() => (confirmAccount = true)}
			disabled={busy}
		>
			Delete account
		</Button>
	</div>
</div>

<ConfirmDialog
	bind:open={confirmCookies}
	title="Remove the cookies for “{account.label}”?"
	description="The account stays, but it cannot be used until you add cookies again."
	confirmLabel="Remove"
	destructive
	onconfirm={() => removeCookies.mutate()}
/>

<ConfirmDialog
	bind:open={confirmAccount}
	title="Delete “{account.label}”?"
	description="The account and its cookies are deleted. Videos that need it will fail until you add another."
	confirmLabel="Delete"
	destructive
	onconfirm={() => removeAccount.mutate()}
/>
