<!--
	Settings: saved tag filters for browsing. A preset lists tags a video must have and tags that
	hide it. The default preset applies on Home, Library, channel and creator pages;
	search, collections, Continue watching, and Up next are never filtered.
-->
<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { toast } from 'svelte-sonner';
	import { api, call, errorMessage, type FilterPreset } from '#lib/api/client.js';
	import { keys, queries } from '#lib/api/queries.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Badge } from '#lib/components/ui/badge/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { Label } from '#lib/components/ui/label/index.js';
	import { Skeleton } from '#lib/components/ui/skeleton/index.js';
	import TagInput from '#lib/components/app/tag-input.svelte';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import Trash2Icon from '@lucide/svelte/icons/trash-2';

	const queryClient = useQueryClient();
	const book = createQuery(() => queries.presets());

	// `editing`: a preset id, 'new', or null when the form is closed.
	let editing = $state<number | 'new' | null>(null);
	let name = $state('');
	let include = $state<string[]>([]);
	let exclude = $state<string[]>([]);

	function open(preset?: FilterPreset) {
		editing = preset ? preset.id : 'new';
		name = preset?.name ?? '';
		include = [...(preset?.include ?? [])];
		exclude = [...(preset?.exclude ?? [])];
	}

	function refresh() {
		queryClient.invalidateQueries({ queryKey: keys.presets });
		// Lists were filtered by the old rules.
		queryClient.invalidateQueries({ queryKey: keys.videos });
	}

	const save = createMutation(() => ({
		mutationFn: () => {
			const body = { name, include, exclude };
			return editing === 'new'
				? call(api.POST('/api/presets', { body }))
				: call(
						api.PUT('/api/presets/{preset_id}', {
							params: { path: { preset_id: editing as number } },
							body
						})
					);
		},
		onSuccess: () => {
			toast.success('Preset saved');
			editing = null;
			refresh();
		},
		onError: (error) => toast.error(errorMessage(error))
	}));

	const remove = createMutation(() => ({
		mutationFn: (id: number) =>
			call(api.DELETE('/api/presets/{preset_id}', { params: { path: { preset_id: id } } })),
		onSuccess: () => {
			toast.success('Preset deleted');
			refresh();
		},
		onError: (error) => toast.error(errorMessage(error))
	}));

	const makeDefault = createMutation(() => ({
		mutationFn: (id: number | null) =>
			call(api.PUT('/api/presets/default', { body: { preset_id: id } })),
		onSuccess: refresh,
		onError: (error) => toast.error(errorMessage(error))
	}));
</script>

<div class="space-y-4">
	{#if book.isPending}
		<Skeleton class="h-16 w-full rounded-xl" />
	{:else}
		{#if book.data?.presets.length}
			<ul class="divide-y overflow-hidden rounded-xl border">
				{#each book.data.presets as preset (preset.id)}
					{@const isDefault = book.data.default_id === preset.id}
					<li class="flex flex-wrap items-center gap-x-3 gap-y-2 p-3">
						<div class="min-w-0 flex-1 space-y-1.5">
							<div class="flex items-center gap-2 text-sm font-medium">
								{preset.name}
								{#if isDefault}<Badge>Default</Badge>{/if}
							</div>
							<div class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
								{#if preset.include.length}
									Only with
									{#each preset.include as tag (tag)}<Badge variant="outline">{tag}</Badge>{/each}
								{/if}
								{#if preset.exclude.length}
									Hides
									{#each preset.exclude as tag (tag)}<Badge variant="outline">{tag}</Badge>{/each}
								{/if}
								{#if !preset.include.length && !preset.exclude.length}Shows everything{/if}
							</div>
						</div>
						<div class="flex items-center gap-1">
							<Button
								variant="outline"
								size="sm"
								disabled={makeDefault.isPending}
								onclick={() => makeDefault.mutate(isDefault ? null : preset.id)}
							>
								{isDefault ? 'Remove default' : 'Make default'}
							</Button>
							<Button variant="ghost" size="icon-sm" aria-label="Edit" onclick={() => open(preset)}>
								<PencilIcon />
							</Button>
							<Button
								variant="ghost"
								size="icon-sm"
								aria-label="Delete"
								disabled={remove.isPending}
								onclick={() => remove.mutate(preset.id)}
							>
								<Trash2Icon />
							</Button>
						</div>
					</li>
				{/each}
			</ul>
		{:else if editing === null}
			<p class="text-sm text-muted-foreground">
				No presets yet. Make one to hide tags you rarely want to see, or to browse only some.
			</p>
		{/if}

		{#if editing !== null}
			<form
				class="space-y-4 rounded-xl border p-4"
				onsubmit={(e) => {
					e.preventDefault();
					save.mutate();
				}}
			>
				<div class="space-y-2">
					<Label for="preset-name">Name</Label>
					<Input id="preset-name" class="max-w-sm" maxlength={60} bind:value={name} />
				</div>
				<div class="space-y-2">
					<Label>Hide videos with these tags</Label>
					<TagInput bind:tags={exclude} label="Tags to hide" />
				</div>
				<div class="space-y-2">
					<Label>Only show videos that have all of these tags (optional)</Label>
					<TagInput bind:tags={include} label="Tags required" />
				</div>
				<div class="flex gap-2">
					<Button type="submit" disabled={save.isPending || !name.trim()}>Save</Button>
					<Button type="button" variant="ghost" onclick={() => (editing = null)}>Cancel</Button>
				</div>
			</form>
		{:else}
			<Button variant="outline" size="sm" onclick={() => open()}><PlusIcon /> New preset</Button>
		{/if}
	{/if}
</div>
