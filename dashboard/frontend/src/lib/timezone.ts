/**
 * timezone.ts — runtime timezone config fetched from /api/v1/config.
 *
 * TIMEZONE is exported as a plain mutable string. Call initTimezone() once
 * at app startup (in +layout.svelte onMount) before any rendering that
 * depends on it. The default is 'Europe/London' so UK users see correct
 * times even on the very first render before the fetch completes.
 */

export let TIMEZONE: string = 'Europe/London';

export async function initTimezone(): Promise<void> {
	try {
		const res = await fetch('/api/v1/config');
		if (res.ok) {
			const data = (await res.json()) as { timezone?: string };
			if (data.timezone) TIMEZONE = data.timezone;
		}
	} catch {
		// Silently keep the default — dashboard still works.
	}
}
