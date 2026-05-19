/**
 * Runtime timezone and station name, fetched from /api/v1/config at startup.
 *
 * TIMEZONE and STATION_NAME are plain mutable module-level variables. Call
 * initTimezone() once in +layout.svelte's onMount before any rendering that
 * depends on them. The defaults below are used for the initial render while
 * the fetch is in flight.
 */

export let TIMEZONE: string = 'Europe/London';
export let STATION_NAME: string = 'BirdNet-UK';

interface RuntimeConfig {
	timezone?: string;
	station_name?: string;
}

/** Fetch timezone and station name from the backend and update the module variables. */
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
		// Keep the defaults — the dashboard still works without server config.
	}
	return null;
}
