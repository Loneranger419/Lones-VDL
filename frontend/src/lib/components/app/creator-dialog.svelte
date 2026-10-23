<!-- Create or edit a creator: a person/brand that links channels across platforms. -->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';
	import { api, call, type Creator } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import ChannelAvatar from './channel-avatar.svelte';

	let {
		open = $bindable(false),
		creator,
		channelIds = []
	}: {
		open?: boolean;
		/** Edit this creator; omit to create a new one. */
		creator?: Creator;
		/** Channels pre-selected for a new creator. */
		channelIds?: number[];
	} = $props();

	let name = $state('');
	let notes = $state('');
	let selected = $state<number[]>([]);

	const channels = createQuery(() => ({ ...queries.channels(), enabled: open }));
	const queryClient = useQueryClient();

	// Reset the form each time the dialog opens.
	$effect.pre(() => {
		if (!open) return;
		name = creator?.name ?? '';
		notes = creator?.notes ?? '';
		selected = creator ? creator.channels.map((c) => c.id) : [...channelIds];
	});

	function toggle(id: number, on: boolean) {
		selected = on ? [...selected, id] : selected.filter((x) => x !== id);
	}

	const save = createMutation(() => ({
		mutationFn: () => {
			const body = { name: name.trim(), notes: notes.trim() || null, channel_ids: selected };
			return creator
				? call(
						api.PATCH('/api/creators/{creator_pk}', {
							params: { path: { creator_pk: creator.id } },
							body
						})
					)
				: call(api.POST('/api/creators', { body }));
		},
		onSuccess: (saved) => {
			queryClient.invalidateQueries({ queryKey: keys.creators });
			queryClient.invalidateQueries({ queryKey: keys.channels });
			open = false;
			if (!creator) {
				toast.success(`Created ${saved.name}`);
				goto(`/creators/${saved.id}`);
			}
		},
		onError: (e) => toast.error(e.message)
	}));
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>{creator ? 'Edit creator' : 'New creator'}</Dialog.Title>
			<Dialog.Description>
				Group the channels one person or brand runs, on any platform, into a single page.
			</Dialog.Description>
		</Dialog.Header>
		<form
			class="space-y-4"
			onsubmit={(e) => {
				e.preventDefault();
				if (name.trim()) save.mutate();
			}}
		>
			<div class="space-y-2">
				<Label for="creator-name">Name</Label>
				<Input id="creator-name" bind:value={name} maxlength={200} required />
			</div>
			<div class="space-y-2">
				<Label for="creator-notes">Notes (optional)</Label>
				<Textarea id="creator-notes" bind:value={notes} rows={2} />
			</div>
			<fieldset class="space-y-2">
				<legend class="mb-2 text-sm font-medium">Channels</legend>
				<div class="max-h-64 space-y-1 overflow-y-auto rounded-lg border p-1">
					{#each channels.data ?? [] as channel (channel.id)}
						{@const taken = channel.creator_pk !== null && channel.creator_pk !== creator?.id}
						<label
							class="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-muted"
						>
							<Checkbox
								checked={selected.includes(channel.id)}
								onCheckedChange={(on) => toggle(channel.id, on)}
							/>
							<ChannelAvatar {channel} class="size-7" />
							<span class="min-w-0 flex-1 truncate text-sm">{channel.name ?? channel.handle}</span>
							{#if taken}
								<span class="text-xs text-muted-foreground">
									{selected.includes(channel.id) ? 'moves here' : 'linked elsewhere'}
								</span>
							{/if}
						</label>
					{:else}
						<p class="p-3 text-sm text-muted-foreground">
							{channels.isPending ? 'Loading…' : 'No channels archived yet.'}
						</p>
					{/each}
				</div>
			</fieldset>
			<Dialog.Footer>
				<Button type="submit" disabled={!name.trim() || save.isPending}>
					{creator ? 'Save' : 'Create'}
				</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
