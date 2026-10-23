/** Display formatting. Dates from the API are ISO strings (UTC). */

export function duration(seconds: number | null | undefined): string {
	if (seconds == null || !Number.isFinite(seconds)) return '';
	const s = Math.max(0, Math.floor(seconds));
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const sec = String(s % 60).padStart(2, '0');
	return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

export function bytes(value: number | null | undefined): string {
	if (value == null) return '';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	let v = value;
	let unit = 0;
	while (v >= 1024 && unit < units.length - 1) {
		v /= 1024;
		unit++;
	}
	return `${v >= 100 || unit === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[unit]}`;
}

export function speed(bytesPerSecond: number | null | undefined): string {
	return bytesPerSecond ? `${bytes(bytesPerSecond)}/s` : '';
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
	['year', 365 * 86400],
	['month', 30 * 86400],
	['week', 7 * 86400],
	['day', 86400],
	['hour', 3600],
	['minute', 60]
];

export function ago(iso: string | null | undefined): string {
	if (!iso) return '';
	const diff = (new Date(iso).getTime() - Date.now()) / 1000;
	for (const [unit, size] of STEPS) {
		if (Math.abs(diff) >= size) return relative.format(Math.round(diff / size), unit);
	}
	return 'just now';
}

/** Upload dates are calendar dates ("2024-01-02"); show them without timezone shifts. */
export function calendarDate(value: string | null | undefined): string {
	if (!value) return '';
	const [y, m, d] = value.split('-').map(Number);
	return new Date(y, m - 1, d).toLocaleDateString(undefined, {
		year: 'numeric',
		month: 'short',
		day: 'numeric'
	});
}

export function dateTime(iso: string | null | undefined): string {
	return iso ? new Date(iso).toLocaleString() : '';
}

export function count(n: number | null | undefined, noun: string): string {
	if (n == null) return '';
	const compact = new Intl.NumberFormat(undefined, { notation: 'compact' }).format(n);
	return `${compact} ${noun}${n === 1 ? '' : 's'}`;
}

export const QUALITY_LABELS: Record<string, string> = {
	best: 'Best available',
	'2160': '4K (2160p)',
	'1440': '1440p',
	'1080': '1080p',
	'720': '720p',
	'480': '480p',
	'360': '360p',
	audio: 'Audio only'
};

export const KIND_LABELS: Record<string, string> = {
	video: 'Video',
	short: 'Short',
	stream: 'Stream'
};
