<!--
	App-wide notices about YouTube access: broken account cookies, a rate-limit pause, and videos
	waiting for approval to use the personal account.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { createQuery } from '@tanstack/svelte-query';
	import { queries } from '#lib/api/queries.js';
	import { accountProblems } from '#lib/accounts.js';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import PauseIcon from '@lucide/svelte/icons/circle-pause';
	import ShieldQuestionIcon from '@lucide/svelte/icons/shield-question-mark';

	const accounts = createQuery(() => queries.accounts());
	const policy = createQuery(() => queries.policy());
	const counts = createQuery(() => queries.jobCounts());

	type Notice = {
		key: string;
		level: 'error' | 'warning';
		message: string;
		href: string;
		action: string;
		icon: typeof TriangleAlertIcon;
	};

	const notices = $derived.by(() => {
		const list: Notice[] = [];
		if (page.url.pathname !== '/health') {
			for (const p of accountProblems(accounts.data)) {
				list.push({
					key: p.message,
					level: p.level,
					message: p.message,
					href: '/health#accounts',
					action: 'Fix account',
					icon: TriangleAlertIcon
				});
			}
		}
		const until = policy.data?.paused_until;
		if (until && new Date(until).getTime() > Date.now()) {
			list.push({
				key: 'paused',
				level: 'warning',
				message: `YouTube is limiting requests, so downloads are paused until ${new Date(until).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}.`,
				href: '/health',
				action: 'Details',
				icon: PauseIcon
			});
		}
		const waiting = counts.data?.awaiting_approval ?? 0;
		if (waiting && page.url.searchParams.get('tab') !== 'approval') {
			list.push({
				key: 'approval',
				level: 'warning',
				message: `${waiting} ${waiting === 1 ? 'video needs' : 'videos need'} your approval to use your personal account.`,
				href: '/downloads?tab=approval',
				action: 'Review',
				icon: ShieldQuestionIcon
			});
		}
		return list;
	});
</script>

{#each notices as notice (notice.key)}
	<div
		role="alert"
		class={[
			'flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2 text-sm',
			notice.level === 'error'
				? 'border-brand-red/30 bg-brand-red/10 text-foreground'
				: 'border-warning/30 bg-warning/10 text-foreground'
		]}
	>
		<notice.icon
			class={['size-4 shrink-0', notice.level === 'error' ? 'text-brand-red' : 'text-warning']}
		/>
		<span class="flex-1">{notice.message}</span>
		<a href={notice.href} class="font-medium text-primary underline-offset-4 hover:underline">
			{notice.action}
		</a>
	</div>
{/each}
