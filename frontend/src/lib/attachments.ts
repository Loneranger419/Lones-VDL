import type { Attachment } from 'svelte/attachments';

/** Calls `callback` whenever the element scrolls into view (or near it). */
export function onVisible(callback: () => void, rootMargin = '600px'): Attachment<HTMLElement> {
	return (element) => {
		const observer = new IntersectionObserver(
			(entries) => {
				if (entries.some((e) => e.isIntersecting)) callback();
			},
			{ rootMargin }
		);
		observer.observe(element);
		return () => observer.disconnect();
	};
}
