<script lang="ts">
	import './layout.css';
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from '#lib/components/ui/sonner/index.js';
	import { ApiError } from '#lib/api/client.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				staleTime: 30_000,
				// Client errors (404, 409, ...) will not fix themselves on retry.
				retry: (failures, error) =>
					!(error instanceof ApiError && error.status < 500) && failures < 2
			}
		}
	});
</script>

<svelte:head>
	<title>Lones-VDL</title>
</svelte:head>

<ModeWatcher defaultMode="dark" themeColors={{ dark: '#0f1420', light: '#f9fafc' }} />
<Toaster position="top-center" richColors closeButton />
<QueryClientProvider client={queryClient}>
	{@render children()}
</QueryClientProvider>
