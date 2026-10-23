<script lang="ts">
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { ui } from '#lib/ui-state.svelte.js';
	import AddDownloadForm from './add-download-form.svelte';
</script>

<Dialog.Root bind:open={ui.addOpen}>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>Add to archive</Dialog.Title>
			<Dialog.Description>Paste a YouTube video, playlist, or channel link.</Dialog.Description>
		</Dialog.Header>
		<AddDownloadForm bind:url={ui.addUrl} onqueued={() => (ui.addOpen = false)} />
	</Dialog.Content>
</Dialog.Root>
