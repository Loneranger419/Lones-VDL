<!--
	YouTube access: import, test, and remove the cookies file. The server filters the upload to
	allowed domains and never sends cookie values back; this panel only ever sees names and dates.
-->
<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Card from '#lib/components/ui/card/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';
	import { api, call, type Schemas } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { cookieProblem } from '#lib/cookies.js';
	import { ago, calendarDate } from '#lib/format.js';
	import ConfirmDialog from './confirm-dialog.svelte';
	import UploadIcon from '@lucide/svelte/icons/upload';
	import FlaskIcon from '@lucide/svelte/icons/flask-conical';
	import TrashIcon from '@lucide/svelte/icons/trash-2';
	import LoaderIcon from '@lucide/svelte/icons/loader-circle';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import InfoIcon from '@lucide/svelte/icons/info';

	const queryClient = useQueryClient();
	const cookies = createQuery(() => queries.cookies());
	const status = $derived(cookies.data);
	const problem = $derived(cookieProblem(status));

	let pasted = $state('');
	let showPaste = $state(false);
	let dragging = $state(false);
	let fileInput = $state<HTMLInputElement>();
	let lastImport = $state<Schemas['CookieImportOut'] | null>(null);
	let confirmRemove = $state(false);

	const refresh = () => {
		queryClient.invalidateQueries({ queryKey: keys.cookies });
		queryClient.invalidateQueries({ queryKey: keys.jobs });
	};

	const upload = createMutation(() => ({
		mutationFn: (text: string) =>
			call(
				api.POST('/api/cookies', {
					body: text,
					bodySerializer: (body: string) => body,
					headers: { 'Content-Type': 'text/plain' }
				})
			),
		onSuccess: (result) => {
			lastImport = result;
			pasted = '';
			showPaste = false;
			queryClient.setQueryData(keys.cookies, result.status);
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
		mutationFn: () => call(api.POST('/api/cookies/test')),
		onSuccess: (health) => {
			refresh();
			if (health.status === 'ok') toast.success('YouTube accepted the cookies');
			else toast.error('Cookie test failed', { description: health.detail ?? health.status });
		},
		onError: (e) => toast.error(e.message)
	}));

	const remove = createMutation(() => ({
		mutationFn: () => call(api.DELETE('/api/cookies')),
		onSuccess: () => {
			lastImport = null;
			refresh();
			toast.success('Cookies removed');
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
		missing: { label: 'Missing', tone: 'bg-brand-red/15 text-brand-red' }
	};
	const health = $derived(
		status?.present
			? (HEALTH[status.health?.status ?? 'untested'] ?? HEALTH.untested)
			: HEALTH.missing
	);

	const loginNames = $derived(Object.keys(status?.login_cookies ?? {}).sort());
	const busy = $derived(upload.isPending || test.isPending || remove.isPending);
</script>

<Card.Root id="cookies" class="scroll-mt-20">
	<Card.Header>
		<Card.Title class="flex items-center gap-2">
			YouTube access
			<span class={['rounded-full px-2 py-0.5 text-xs font-medium', health.tone]}
				>{health.label}</span
			>
		</Card.Title>
		<Card.Description>
			YouTube only allows downloads from a signed-in browser, so Lones-VDL needs that browser’s
			cookies.
		</Card.Description>
	</Card.Header>
	<Card.Content class="space-y-5">
		{#if problem}
			<Alert.Root variant={problem.level === 'error' ? 'destructive' : 'default'}>
				<TriangleAlertIcon />
				<Alert.Title>{problem.message}</Alert.Title>
			</Alert.Root>
		{/if}

		{#if status?.present}
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
				'rounded-xl border-2 border-dashed p-6 text-center transition-colors',
				dragging ? 'border-primary bg-primary/5' : 'border-border'
			]}
			ondragover={(e) => {
				e.preventDefault();
				dragging = true;
			}}
			ondragleave={() => (dragging = false)}
			{ondrop}
		>
			<UploadIcon class="mx-auto mb-2 size-6 text-muted-foreground" />
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

		{#if lastImport}
			{@const s = lastImport.summary as {
				kept?: number;
				dropped_domain?: number;
				dropped_expired?: number;
				warnings?: string[];
			}}
			<p class="text-sm text-muted-foreground">
				Kept {s.kept ?? 0} YouTube cookies; discarded {s.dropped_domain ?? 0} from other sites{s.dropped_expired
					? ` and ${s.dropped_expired} expired`
					: ''}.
			</p>
			{#each s.warnings ?? [] as warning (warning)}
				<p class="text-sm text-warning">{warning}</p>
			{/each}
		{/if}

		<div class="flex flex-wrap gap-2">
			<Button variant="outline" onclick={() => test.mutate()} disabled={!status?.present || busy}>
				{#if test.isPending}<LoaderIcon class="animate-spin" />{:else}<FlaskIcon />{/if}
				Test
			</Button>
			{#if status?.present}
				<Button variant="ghost" onclick={() => (confirmRemove = true)} disabled={busy}>
					<TrashIcon /> Remove
				</Button>
			{/if}
		</div>

		<details class="group rounded-lg bg-muted/50 p-4 text-sm">
			<summary class="flex cursor-pointer items-center gap-2 font-medium">
				<InfoIcon class="size-4 text-primary" /> How to get a cookies file
			</summary>
			<ol class="mt-3 list-decimal space-y-1.5 pl-5 text-muted-foreground">
				<li>
					Use a <strong class="text-foreground">dedicated Google account</strong> that is age-verified,
					not your personal one.
				</li>
				<li>
					Open a <strong class="text-foreground">private / incognito window</strong> and sign in to youtube.com.
				</li>
				<li>
					Export cookies with a “cookies.txt” browser extension (Netscape format) while on
					youtube.com.
				</li>
				<li>
					<strong class="text-foreground">Close the private window right away.</strong> Browsing on with
					it makes YouTube rotate the cookies and the export stops working.
				</li>
				<li>Drop the file above, then press Test.</li>
			</ol>
		</details>
	</Card.Content>
</Card.Root>

<ConfirmDialog
	bind:open={confirmRemove}
	title="Remove YouTube cookies?"
	description="Downloads will fail until you add a new cookies file."
	confirmLabel="Remove"
	destructive
	onconfirm={() => remove.mutate()}
/>
