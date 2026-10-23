import type { CookieStatus } from '#lib/api/client.js';

export type CookieProblem = { level: 'error' | 'warning'; message: string };

const DAY = 86_400_000;

/** YouTube refuses signed-out downloads, so cookie trouble is shown app-wide. */
export function cookieProblem(status: CookieStatus | undefined): CookieProblem | null {
	if (!status) return null;
	if (!status.present) {
		return {
			level: 'error',
			message: 'No YouTube cookies yet. Downloads will fail until you add them.'
		};
	}
	if (status.health?.status === 'invalid') {
		return {
			level: 'error',
			message: 'YouTube rejected the saved cookies. Export fresh ones from a private window.'
		};
	}
	if (status.login_expires) {
		const days = (new Date(status.login_expires).getTime() - Date.now()) / DAY;
		if (days < 0) return { level: 'error', message: 'Your YouTube cookies have expired.' };
		if (days < 7) {
			return {
				level: 'warning',
				message: `Your YouTube cookies expire in ${Math.ceil(days)} days.`
			};
		}
	}
	return null;
}
