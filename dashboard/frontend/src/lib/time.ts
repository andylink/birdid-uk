/**
 * Date/time formatting utilities for the dashboard.
 *
 * All functions take ISO 8601 strings (with +00:00 suffix as returned by the
 * API) and format them in the user's configured local timezone.
 */

import { TIMEZONE } from './timezone';

/** Format a UTC timestamp as a local time string, e.g. "15:30:22". */
export function formatTime(isoStr: string): string {
	return new Date(isoStr).toLocaleTimeString('en-GB', {
		hour: '2-digit',
		minute: '2-digit',
		second: '2-digit',
		timeZone: TIMEZONE
	});
}

/** Format a UTC timestamp as a short local date, e.g. "10 May". */
export function formatDate(isoStr: string): string {
	return new Date(isoStr).toLocaleDateString('en-GB', {
		day: 'numeric',
		month: 'short',
		timeZone: TIMEZONE
	});
}

/** Format a UTC timestamp as a full local date, e.g. "10 May 2026". */
export function formatFullDate(isoStr: string): string {
	return new Date(isoStr).toLocaleDateString('en-GB', {
		day: 'numeric',
		month: 'short',
		year: 'numeric',
		timeZone: TIMEZONE
	});
}

/**
 * Return today's date as YYYY-MM-DD in the configured timezone.
 * Uses the en-CA locale because it natively produces YYYY-MM-DD output.
 */
export function localToday(): string {
	return new Date().toLocaleDateString('en-CA', { timeZone: TIMEZONE });
}

/** Extract the local hour (0–23) from a UTC timestamp string. */
export function localHour(isoStr: string): number {
	const hourStr = new Date(isoStr).toLocaleString('en-GB', {
		hour: '2-digit',
		hour12: false,
		timeZone: TIMEZONE
	});
	return parseInt(hourStr, 10);
}
