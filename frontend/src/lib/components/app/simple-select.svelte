<script lang="ts">
	import * as Select from '#lib/components/ui/select/index.js';

	type Option = { value: string; label: string };
	let {
		value = $bindable(''),
		options,
		onchange,
		placeholder = 'Select…',
		class: className = '',
		size = 'default',
		disabled = false,
		label
	}: {
		value?: string;
		options: Option[];
		onchange?: (value: string) => void;
		placeholder?: string;
		class?: string;
		size?: 'sm' | 'default';
		disabled?: boolean;
		/** Accessible name when there is no visible label. */
		label?: string;
	} = $props();

	const current = $derived(options.find((o) => o.value === value));
</script>

<Select.Root
	type="single"
	bind:value
	onValueChange={(v) => onchange?.(v)}
	{disabled}
	items={options}
>
	<Select.Trigger class={className} {size} aria-label={label}>
		{current?.label ?? placeholder}
	</Select.Trigger>
	<Select.Content>
		{#each options as option (option.value)}
			<Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
		{/each}
	</Select.Content>
</Select.Root>
