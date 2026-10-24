import type { Account } from '#lib/api/client.js';

export type AccessProblem = { level: 'error' | 'warning'; message: string };

const DAY = 86_400_000;

export const ROLE_LABELS: Record<Account['role'], string> = {
	alternate: 'Alternate',
	personal: 'Personal'
};

/**
 * Problems with the accounts' cookies. Having no account is fine: most public videos download
 * anonymously, and the app says so when one that needs an account fails.
 */
export function accountProblems(accounts: Account[] | undefined): AccessProblem[] {
	const problems: AccessProblem[] = [];
	for (const account of accounts ?? []) {
		const { status, label } = account;
		if (!account.enabled || !status.present) continue;
		if (status.health?.status === 'invalid') {
			problems.push({
				level: 'error',
				message: `YouTube rejected the cookies for “${label}”. Export fresh ones from a private window.`
			});
			continue;
		}
		if (status.login_expires) {
			const days = (new Date(status.login_expires).getTime() - Date.now()) / DAY;
			if (days < 0) {
				problems.push({ level: 'error', message: `The sign-in for “${label}” has expired.` });
			} else if (days < 7) {
				problems.push({
					level: 'warning',
					message: `The sign-in for “${label}” expires in ${Math.ceil(days)} days.`
				});
			}
		}
	}
	return problems;
}

/** The worst problem, for a single indicator. */
export function worstProblem(problems: AccessProblem[]): AccessProblem | null {
	return problems.find((p) => p.level === 'error') ?? problems[0] ?? null;
}
