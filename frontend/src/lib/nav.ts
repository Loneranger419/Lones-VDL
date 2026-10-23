import type { Component } from 'svelte';
import HouseIcon from '@lucide/svelte/icons/house';
import LibraryIcon from '@lucide/svelte/icons/library-big';
import DownloadIcon from '@lucide/svelte/icons/download';
import TvIcon from '@lucide/svelte/icons/tv';
import ListVideoIcon from '@lucide/svelte/icons/list-video';
import ActivityIcon from '@lucide/svelte/icons/activity';
import SettingsIcon from '@lucide/svelte/icons/settings';

export type NavItem = {
	href: string;
	label: string;
	icon: Component;
	mobile?: boolean;
	/** Other paths that belong to this section. */
	also?: string[];
};

export const mainNav: NavItem[] = [
	{ href: '/', label: 'Home', icon: HouseIcon, mobile: true },
	{ href: '/library', label: 'Library', icon: LibraryIcon, mobile: true },
	{ href: '/downloads', label: 'Downloads', icon: DownloadIcon, mobile: true },
	{ href: '/channels', label: 'Channels', icon: TvIcon, mobile: true, also: ['/creators'] },
	{ href: '/collections', label: 'Collections', icon: ListVideoIcon }
];

export const systemNav: NavItem[] = [
	{ href: '/health', label: 'Health', icon: ActivityIcon },
	{ href: '/settings', label: 'Settings', icon: SettingsIcon }
];

function under(pathname: string, href: string): boolean {
	return href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(href + '/');
}

export function isActive(pathname: string, item: NavItem): boolean {
	return [item.href, ...(item.also ?? [])].some((href) => under(pathname, href));
}
