<script lang="ts">
	import { goto } from '$app/navigation';
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';
	import { api, call } from '#lib/api/client.js';
	import { keys } from '#lib/api/queries.js';

	let {
		open = $bindable(false),
		videoIds = [],
		navigate = false
	}: {
		open?: boolean;
		/** Videos to put in the new collection right away. */
		videoIds?: number[];
		/** Open the collection page after creating it. */
		navigate?: boolean;
	} = $props();

	let name = $state('');
	let description = $state('');
	const queryClient = useQueryClient();

	const create = createMutation(() => ({
		mutationFn: async () => {
			const created = await call(
				api.POST('/api/collections', {
					body: { name: name.trim(), description: description.trim() || null }
				})
			);
			if (videoIds.length) {
				await call(
					api.POST('/api/collections/{collection_pk}/items', {
						params: { path: { collection_pk: created.id } },
						body: { video_ids: videoIds }
					})
				);
			}
			return created;
		},
		onSuccess: (created) => {
			queryClient.invalidateQueries({ queryKey: keys.collections });
			queryClient.invalidateQueries({ queryKey: keys.videos });
			toast.success(
				videoIds.length ? `Added to new collection ${created.name}` : `Created ${created.name}`
			);
			open = false;
			name = '';
			description = '';
			if (navigate) goto(`/collections/${created.id}`);
		},
		onError: (e) => toast.error(e.message)
	}));
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>New collection</Dialog.Title>
			<Dialog.Description>Your own ordered list of archived videos.</Dialog.Description>
		</Dialog.Header>
		<form
			class="space-y-4"
			onsubmit={(e) => {
				e.preventDefault();
				if (name.trim()) create.mutate();
			}}
		>
			<div class="space-y-2">
				<Label for="collection-name">Name</Label>
				<Input id="collection-name" bind:value={name} maxlength={200} required />
			</div>
			<div class="space-y-2">
				<Label for="collection-description">Description (optional)</Label>
				<Textarea id="collection-description" bind:value={description} rows={3} />
			</div>
			<Dialog.Footer>
				<Button type="submit" disabled={!name.trim() || create.isPending}>Create</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
