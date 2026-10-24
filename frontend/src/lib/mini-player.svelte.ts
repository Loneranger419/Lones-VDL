/** The video that keeps playing in a small floating player after leaving its Watch page. */
import type { Track } from '#lib/components/app/player.svelte';

export type MiniVideo = {
	id: number;
	title: string;
	src: string;
	poster?: string;
	tracks: Track[];
	/** Seconds to continue from. */
	position: number;
};

export const mini = $state<{ video: MiniVideo | null }>({ video: null });
