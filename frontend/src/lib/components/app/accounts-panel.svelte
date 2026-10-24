<!--
	YouTube accounts. Downloads try without signing in first; an "alternate" account is used when
	YouTube refuses, and a "personal" account only for videos the user approves.
-->
<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Card from '#lib/components/ui/card/index.js';
	import * as Alert from '#lib/components/ui/alert/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import { api, call } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { accountProblems } from '#lib/accounts.js';
	import AccountCard from './account-card.svelte';
	import SimpleSelect from './simple-select.svelte';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import InfoIcon from '@lucide/svelte/icons/info';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';

	const queryClient = useQueryClient();
	const accounts = createQuery(() => queries.accounts());
	const problems = $derived(accountProblems(accounts.data));

	let label = $state('');
	let role = $state<'alternate' | 'personal'>('alternate');

	const roleOptions = [
		{ value: 'alternate', label: 'Alternate (dedicated, age-verified)' },
		{ value: 'personal', label: 'Personal (only with approval)' }
	];

	const create = createMutation(() => ({
		mutationFn: () => call(api.POST('/api/accounts', { body: { label: label.trim(), role } })),
		onSuccess: (account) => {
			label = '';
			queryClient.invalidateQueries({ queryKey: keys.accounts });
			toast.success(`Added “${account.label}”`, { description: 'Now add its cookies below.' });
		},
		onError: (e) => toast.error(e.message)
	}));
</script>

<Card.Root id="accounts" class="scroll-mt-20">
	<Card.Header>
		<Card.Title>YouTube accounts</Card.Title>
		<Card.Description>
			Most public videos download without signing in. When YouTube refuses, the alternate account is
			tried. Your personal account is only used for a video you approve, such as a members-only one.
		</Card.Description>
	</Card.Header>
	<Card.Content class="space-y-5">
		{#each problems as problem (problem.message)}
			<Alert.Root variant={problem.level === 'error' ? 'destructive' : 'default'}>
				<TriangleAlertIcon />
				<Alert.Title>{problem.message}</Alert.Title>
			</Alert.Root>
		{/each}

		{#if accounts.isPending}
			<Skeleton class="h-40 w-full" />
		{:else if accounts.data?.length}
			{#each accounts.data as account (account.id)}
				<AccountCard {account} />
			{/each}
		{:else}
			<p class="rounded-lg bg-muted/50 p-4 text-sm text-muted-foreground">
				No accounts yet. Downloads run without signing in, so age-restricted videos and YouTube bot
				checks will fail until you add an alternate account.
			</p>
		{/if}

		<form
			class="flex flex-wrap items-end gap-2"
			onsubmit={(e) => {
				e.preventDefault();
				if (label.trim()) create.mutate();
			}}
		>
			<div class="min-w-40 flex-1 space-y-1.5">
				<label for="new-account" class="text-sm font-medium">Add an account</label>
				<Input
					id="new-account"
					bind:value={label}
					placeholder="Name, for example Alternate"
					maxlength={100}
					autocomplete="off"
				/>
			</div>
			<SimpleSelect class="w-64" label="Account type" options={roleOptions} bind:value={role} />
			<Button type="submit" disabled={!label.trim() || create.isPending}>
				<PlusIcon /> Add
			</Button>
		</form>

		<details class="group rounded-lg bg-muted/50 p-4 text-sm">
			<summary class="flex cursor-pointer items-center gap-2 font-medium">
				<InfoIcon class="size-4 text-primary" /> How to get a cookies file
			</summary>
			<ol class="mt-3 list-decimal space-y-1.5 pl-5 text-muted-foreground">
				<li>
					For the alternate account, use a <strong class="text-foreground"
						>dedicated Google account</strong
					>
					that is age-verified, not your personal one.
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
				<li>Drop the file on the account above, then press Test.</li>
			</ol>
			<p class="mt-3 text-muted-foreground">
				Cookies are secrets. They are stored on the server only, never shown here, and never written
				to logs. No limit or pause guarantees YouTube won’t restrict an account.
			</p>
		</details>
	</Card.Content>
</Card.Root>
