/**
 * timezone.ts — runtime timezone and station-name config fetched from /api/v1/config.
 *
 * TIMEZONE and STATION_NAME are exported as plain mutable strings. Call
 * initTimezone() once at app startup (in +layout.svelte onMount) before any
 * rendering that depends on them. The defaults handle the very first render
 * before the fetch completes.
 */

export let TIMEZONE: string = 'Europe/London';
export let STATION_NAME: string = 'BirdNet-UK';

interface RuntimeConfig {
	timezone?: string;
	station_name?: string;
}

export async function initTimezone(): Promise<RuntimeConfig | null> {
	try {
		const res = await fetch('/api/v1/config');
		if (res.ok) {
			const data = (await res.json()) as RuntimeConfig;
			if (data.timezone) TIMEZONE = data.timezone;
			if (data.station_name) STATION_NAME = data.station_name;
			return data;
		}
	} catch {
		// Silently keep the defaults — dashboard still works.
	}
	return null;
}
