<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getDailySpeciesSummary, getSunTimes } from '$lib/api';
	import { createSSE } from '$lib/sse';
	import type { Detection, DailySpeciesSummary, SunTimes } from '$lib/api';
	import { localToday, localHour, formatTime } from '$lib/time';
	import { TIMEZONE } from '$lib/timezone';
	import {
		BOCC_COLOR,
		SPECIES_STATUS_STYLE,
		groupBadgeColor,
		speciesInitials,
	} from '$lib/bto';

	function todayStr(): string { return localToday(); }

	let { selectedDate = $bindable(todayStr()) }: { selectedDate?: string } = $props();

	let summaries  = $state<DailySpeciesSummary[]>([]);
	let loading    = $state(true);
	let error      = $state<string | null>(null);
	let sse: ReturnType<typeof createSSE> | null = null;
	let midnightTimer: ReturnType<typeof setInterval> | null = null;
	let boccFilter = $state<string>('all');
	let sunTimes   = $state<SunTimes | null>(null);

	const HOURS = Array.from({ length: 24 }, (_, i) => i);

	// Cyan scale: index 0 = empty cell, 1–9 = increasing detection intensity
	const HEATMAP_COLORS = [
		'',
		'#082f49',
		'#0c4a6e',
		'#075985',
		'#0369a1',
		'#0284c7',
		'#0ea5e9',
		'#38bdf8',
		'#7dd3fc',
		'#bae6fd',
	] as const;

	const isToday = $derived(selectedDate === todayStr());

	// Sort by total count descending, then by most-recently-heard
	const sortedSummaries = $derived(
		[...summaries].sort((a, b) => {
			if (b.count !== a.count) return b.count - a.count;
			return (b.latest_heard ?? '').localeCompare(a.latest_heard ?? '');
		})
	);

	const filteredSummaries = $derived(
		boccFilter === 'all'
			? sortedSummaries
			: sortedSummaries.filter(s => s.uk_bocc === boccFilter)
	);

	const maxHourlyCount = $derived(
		Math.max(1, ...summaries.flatMap((s) => s.hourly_counts))
	);

	// Extract just the hour from sunrise/sunset HH:MM strings for column highlighting
	const sunriseHour = $derived(
		sunTimes ? parseInt(sunTimes.sunrise.slice(0, 2), 10) : null
	);
	const sunsetHour = $derived(
		sunTimes ? parseInt(sunTimes.sunset.slice(0, 2), 10) : null
	);

	function formatDisplayDate(d: string): string {
		return new Date(d + 'T12:00:00').toLocaleDateString('en-GB', {
			weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
		});
	}

	// Returns a new date string offset by n days; uses noon to avoid DST edge cases
	function addDays(d: string, n: number): string {
		const date = new Date(d + 'T12:00:00');
		date.setDate(date.getDate() + n);
		return date.toISOString().slice(0, 10);
	}

	// Maps a count to one of 9 intensity levels relative to the day's peak
	function getIntensity(count: number): number {
		if (count <= 0) return 0;
		return Math.min(9, Math.max(1, Math.ceil((count / maxHourlyCount) * 9)));
	}

	async function fetchData(date: string, { showLoading = true }: { showLoading?: boolean } = {}) {
		if (showLoading) {
			loading = true;
			error = null;
		}
		try {
			[summaries, sunTimes] = await Promise.all([
				getDailySpeciesSummary(date),
				getSunTimes(date),
			]);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Could not load species data';
			summaries = [];
			sunTimes = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => { void fetchData(selectedDate); });

	function prevDay()   { selectedDate = addDays(selectedDate, -1); }
	function nextDay()   { if (!isToday) selectedDate = addDays(selectedDate, 1); }
	function goToToday() { selectedDate = todayStr(); }

	function handleDateInput(e: Event) {
		const val = (e.target as HTMLInputElement).value;
		if (val && val <= todayStr()) selectedDate = val;
	}

	// Keep heatmap live for today: on each new detection, update the relevant row in place
	onMount(() => {
		sse = createSSE('/stream/detections');

		// On reconnect, silently refresh to catch any events missed during the gap.
		// Skip the very first 'open' — the $effect already handles the initial data load.
		let sseEverOpened = false;
		sse.on('open', () => {
			if (sseEverOpened) {
				void fetchData(selectedDate, { showLoading: false });
			}
			sseEverOpened = true;
		});

		sse.on('detection', (raw) => {
			const d = raw as Detection;
			if (selectedDate !== todayStr()) return;
			const detectionDay = new Date(d.timestamp).toLocaleDateString('en-CA', {
				timeZone: TIMEZONE
			});
			if (detectionDay !== todayStr()) return;

			const hour = localHour(d.timestamp);
			const idx  = summaries.findIndex((s) => s.species === d.species);

			if (idx >= 0) {
				// Update existing row immutably
				const updated = { ...summaries[idx] };
				updated.count++;
				updated.hourly_counts = [...updated.hourly_counts];
				updated.hourly_counts[hour] = (updated.hourly_counts[hour] ?? 0) + 1;
				updated.latest_heard = formatTime(d.timestamp);
				summaries = [
					...summaries.slice(0, idx),
					updated,
					...summaries.slice(idx + 1),
				];
			} else {
				// First detection of this species today — add a new row
				const hc = new Array(24).fill(0);
				hc[hour] = 1;
				summaries = [{
					species:          d.species,
					scientific_name:  d.scientific_name,
					group_name:       d.group_name,
					uk_bocc:          d.uk_bocc,
					species_status:   d.species_status,
					bto_2letter_code: d.bto_2letter_code,
					bto_5letter_code: d.bto_5letter_code,
					count:            1,
					hourly_counts:    hc,
					first_heard:      formatTime(d.timestamp),
					latest_heard:     formatTime(d.timestamp),
				}, ...summaries];
			}
		});

		// Advance selectedDate when local midnight passes (for dashboards left open overnight).
		// We check every 60 s; if the calendar day has rolled over and the user was on
		// the old "today", move them forward to the new one so live SSE updates continue.
		let knownToday = localToday();
		midnightTimer = setInterval(() => {
			const newToday = localToday();
			if (newToday !== knownToday) {
				if (selectedDate === knownToday) selectedDate = newToday;
				knownToday = newToday;
			}
		}, 60_000);
	});

	onDestroy(() => {
		sse?.close();
		if (midnightTimer !== null) clearInterval(midnightTimer);
	});
</script>

<section class="heatmap" aria-label="Daily species heatmap">

	<header class="hm-header">
		<h2 class="hm-title">Daily Species Summary</h2>

		{#if !loading && !error}
			<span class="hm-date">{formatDisplayDate(selectedDate)}</span>
			{#if summaries.length > 0}
				<span class="hm-count">
					{filteredSummaries.length}{boccFilter !== 'all' ? `/${summaries.length}` : ''} species
					· {filteredSummaries.reduce((t, s) => t + s.count, 0)} detections
				</span>
			{/if}
		{/if}

		<!-- Filter by BoCC conservation list colour -->
		{#if !loading && !error && summaries.length > 0}
			<div class="bocc-filters">
				{#each [['all', 'All', ''], ['Red', 'Red', '#ef4444'], ['Amber', 'Amber', '#f59e0b'], ['Green', 'Green', '#22c55e']] as [val, label, color]}
					<button
						class="filter-btn"
						class:active={boccFilter === val}
						style={boccFilter === val && color ? `border-color: ${color}; color: ${color}` : ''}
						onclick={() => boccFilter = val}
						aria-pressed={boccFilter === val}
					>
						{#if color}
							<span class="bocc-dot" style="background-color: {color}"></span>
						{/if}{label}
					</button>
				{/each}
			</div>
		{/if}

		<!-- Prev/next day navigation; date picker for jumping directly -->
		<div class="date-nav">
			<button class="nav-btn" onclick={prevDay} aria-label="Previous day">
				<svg viewBox="0 0 20 20" aria-hidden="true">
					<path d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z"/>
				</svg>
			</button>
			<input
				type="date"
				value={selectedDate}
				max={todayStr()}
				oninput={handleDateInput}
				class="date-input"
				aria-label="Select date"
			/>
			<button
				class="nav-btn"
				onclick={nextDay}
				disabled={isToday}
				aria-label="Next day"
			>
				<svg viewBox="0 0 20 20" aria-hidden="true">
					<path d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"/>
				</svg>
			</button>
			{#if !isToday}
				<button class="today-btn" onclick={goToToday}>Today</button>
			{/if}
		</div>
	</header>

	<div class="hm-scroll">

		{#if loading}
			<div class="hm-skeletons" aria-busy="true" aria-label="Loading…">
				{#each Array.from({ length: 10 }) as _}
					<div class="sk-row skeleton-pulse">
						<div class="sk-name"></div>
						{#each HOURS as _h}
							<div class="sk-cell"></div>
						{/each}
						<div class="sk-total"></div>
					</div>
				{/each}
			</div>

		{:else if error}
			<div class="hm-state">
				<svg viewBox="0 0 24 24" class="state-icon" aria-hidden="true">
					<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
				</svg>
				<p>{error}</p>
			</div>

		{:else if summaries.length === 0}
			<div class="hm-state muted">
				<p>No species detected today.</p>
			</div>

		{:else if filteredSummaries.length === 0}
			<div class="hm-state muted">
				<p>No {boccFilter} list species detected today.</p>
				<button class="show-all-btn" onclick={() => boccFilter = 'all'}>
					Show all species
				</button>
			</div>

		{:else}
			<table class="hm-table" role="grid" aria-label="Species detection heatmap">
				<thead>
					<tr>
						<th scope="col" class="th-species">Species</th>
						{#each HOURS as hour}
							{@const isSunrise = sunriseHour !== null && hour === sunriseHour}
							{@const isSunset  = sunsetHour  !== null && hour === sunsetHour}
							<th
								scope="col"
								class="th-hour"
								class:sunrise={isSunrise}
								class:sunset={isSunset}
								title={isSunrise
									? `Sunrise ${sunTimes!.sunrise}`
									: isSunset
									? `Sunset ${sunTimes!.sunset}`
									: undefined}
							>
								{hour.toString().padStart(2, '0')}
								{#if isSunrise}
									<svg viewBox="0 0 14 12" class="sun-icon" aria-hidden="true">
										<circle cx="7" cy="3.5" r="2.5" fill="#fbbf24"/>
										<line x1="1" y1="7.5" x2="13" y2="7.5" stroke="#fbbf24" stroke-width="1.3" stroke-linecap="round"/>
										<polyline points="4,11 7,8.5 10,11" stroke="#fbbf24" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
									</svg>
								{:else if isSunset}
									<svg viewBox="0 0 14 12" class="sun-icon" aria-hidden="true">
										<polyline points="4,1 7,3.5 10,1" stroke="#fb923c" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
										<line x1="1" y1="4.5" x2="13" y2="4.5" stroke="#fb923c" stroke-width="1.3" stroke-linecap="round"/>
										<circle cx="7" cy="8.5" r="2.5" fill="#fb923c"/>
									</svg>
								{/if}
							</th>
						{/each}
						<th scope="col" class="th-total">Total</th>
					</tr>
				</thead>

				<tbody>
					{#each filteredSummaries as item (item.species)}
						{@const statusStyle = item.species_status ? SPECIES_STATUS_STYLE[item.species_status] : null}
						<tr class="hm-row">
							<td class="td-species">
								<div class="species-cell">
									<!-- Coloured group badge showing BTO code abbreviation -->
									<span
										class="group-badge"
										style="background-color: {groupBadgeColor(item.group_name)}"
										aria-hidden="true"
									>
										{speciesInitials(item.species, item.bto_5letter_code, item.bto_2letter_code)}
									</span>
									{#if item.uk_bocc}
										<span
											class="bocc-dot-sm"
											style="background-color: {BOCC_COLOR[item.uk_bocc] ?? '#94a3b8'}"
											title="UK BoCC: {item.uk_bocc}"
											aria-label="UK Birds of Conservation Concern: {item.uk_bocc}"
										></span>
									{/if}
									<span class="species-link-wrap truncate" title={item.species}>
										<a
											href="/species/{encodeURIComponent(item.species)}?from=dashboard"
											class="species-link"
										>
											{item.species}
										</a>
									</span>
									{#if statusStyle}
										<span
											class="status-badge"
											style="background-color: {statusStyle.bg}; color: {statusStyle.text}"
											title="Species status: {item.species_status}"
										>
											{item.species_status}
										</span>
									{/if}
								</div>
							</td>

							{#each HOURS as hour}
								{@const count     = item.hourly_counts[hour] ?? 0}
								{@const intensity = getIntensity(count)}
								<td
									class="td-hour"
									style={intensity > 0 ? `background-color: ${HEATMAP_COLORS[intensity]}` : ''}
									title={count > 0
										? `${count} detection${count !== 1 ? 's' : ''} at ${hour.toString().padStart(2, '0')}:00`
										: `${hour.toString().padStart(2, '0')}:00 — no detections`}
									role="gridcell"
									aria-label="{item.species} {hour.toString().padStart(2,'0')}:00 {count} detections"
								>
									{#if count > 0}
										<span
											class="hour-count tabular"
											class:light-text={intensity >= 7}
										>
											{count}
										</span>
									{/if}
								</td>
							{/each}

							<td class="td-total tabular">{item.count}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>

	{#if !loading && !error && summaries.length > 0}
		<div class="hm-legend">
			<span class="legend-label">Less</span>
			{#each HEATMAP_COLORS.slice(1) as color, i}
				<div
					class="legend-swatch"
					style="background-color: {color}"
					title="Intensity {i + 1}"
				></div>
			{/each}
			<span class="legend-label">More</span>
			<span class="legend-note">per hour, scaled to peak</span>
		</div>
	{/if}
</section>

<style>
	.heatmap {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--color-page);
		overflow: hidden;
	}

	.hm-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem 1rem;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface);
		flex-shrink: 0;
		flex-wrap: wrap;
		row-gap: 0.5rem;
	}
	.hm-title {
		margin: 0;
		font-size: 0.625rem;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}
	.hm-date {
		font-size: 0.875rem;
		color: var(--color-text-3);
		font-weight: 500;
	}
	.hm-count {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}

	.bocc-filters {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		margin-left: 0.5rem;
	}
	.filter-btn {
		font-size: 0.625rem;
		padding: 0.125rem 0.5rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
		font-weight: 500;
		transition: background-color 0.15s, color 0.15s, border-color 0.15s;
		display: flex;
		align-items: center;
		gap: 0.25rem;
	}
	.filter-btn:hover { color: var(--color-text-3); }
	.filter-btn.active {
		background: var(--color-skeleton);
		border-color: var(--color-border-strong);
		color: var(--color-text);
	}
	.bocc-dot {
		display: inline-block;
		width: 0.375rem;
		height: 0.375rem;
		border-radius: 9999px;
	}

	/* Date nav pushed to the right */
	.date-nav {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 0.375rem;
	}
	.nav-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0.375rem;
		border-radius: 0.25rem;
		border: none;
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
		transition: background-color 0.15s, color 0.15s;
	}
	.nav-btn svg {
		width: 1rem;
		height: 1rem;
		fill: currentColor;
	}
	.nav-btn:hover {
		background: var(--color-skeleton);
		color: var(--color-text);
	}
	.nav-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
	.date-input {
		font-size: 0.75rem;
		background: var(--color-surface-2);
		border: 1px solid var(--color-border-strong);
		color: var(--color-text-2);
		border-radius: 0.25rem;
		padding: 0.25rem 0.5rem;
		cursor: pointer;
	}
	.date-input:focus {
		outline: none;
		border-color: var(--color-accent);
		box-shadow: 0 0 0 1px var(--color-accent-ring);
	}
	.today-btn {
		font-size: 0.75rem;
		padding: 0.25rem 0.625rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-accent-border);
		background: var(--color-accent-muted);
		color: var(--color-accent-text);
		cursor: pointer;
		font-weight: 500;
		transition: background-color 0.15s;
	}
	.today-btn:hover {
		background: rgba(16, 185, 129, 0.25);
	}

	.hm-scroll {
		flex: 1;
		overflow: auto;
		min-height: 0;
	}

	.hm-skeletons { padding: 0.75rem; display: flex; flex-direction: column; gap: 0.25rem; }
	.sk-row { display: flex; gap: 0.125rem; }
	.sk-name  { height: 1.75rem; width: 11rem; background: var(--color-skeleton); border-radius: 0.25rem; flex-shrink: 0; }
	.sk-cell  { height: 1.75rem; width: 2rem; background: color-mix(in srgb, var(--color-skeleton) 40%, transparent); border-radius: 0.125rem; flex-shrink: 0; }
	.sk-total { height: 1.75rem; width: 3rem; background: var(--color-skeleton); border-radius: 0.25rem; flex-shrink: 0; }

	.hm-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 10rem;
		gap: 0.5rem;
		color: var(--color-text-dim);
	}
	.hm-state.muted { color: var(--color-text-ghost); }
	.hm-state p { margin: 0; font-size: 0.875rem; }
	.state-icon { width: 2rem; height: 2rem; fill: currentColor; opacity: 0.4; }
	.show-all-btn {
		font-size: 0.75rem;
		color: var(--color-accent-text);
		background: none;
		border: none;
		cursor: pointer;
		text-decoration: underline;
	}

	.hm-table {
		border-collapse: collapse;
		min-width: max-content;
		width: 100%;
	}

	/* Sticky thead so hour labels scroll with the table horizontally but stay at top */
	thead {
		position: sticky;
		top: 0;
		z-index: 10;
	}

	/* Species column: sticky left so it stays visible on horizontal scroll */
	.th-species {
		position: sticky;
		left: 0;
		z-index: 20;
		background: var(--color-surface);
		padding: 0.375rem 0.75rem;
		text-align: left;
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--color-text-muted);
		border-bottom: 1px solid var(--color-border);
		border-right: 1px solid var(--color-border);
		min-width: 10rem;
	}
	.th-hour {
		width: 2rem;
		min-width: 2rem;
		padding: 0.25rem 0;
		text-align: center;
		font-size: 0.625rem;
		font-family: ui-monospace, monospace;
		font-weight: 400;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface);
		color: var(--color-text-dim);
	}
	.th-hour.sunrise { color: #f59e0b; }
	.th-hour.sunset  { color: #f97316; }
	.sun-icon {
		width: 0.875rem;
		height: 0.75rem;
		display: block;
		margin: 0.125rem auto 0;
	}
	.th-total {
		width: 3rem;
		min-width: 3rem;
		padding: 0.375rem 0.75rem 0.375rem 0;
		text-align: right;
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--color-text-muted);
		border-bottom: 1px solid var(--color-border);
		border-left: 1px solid var(--color-border);
		background: var(--color-surface);
	}

	.hm-row:hover .td-species {
		background: var(--color-skeleton);
	}
	.td-species {
		position: sticky;
		left: 0;
		z-index: 10;
		background: var(--color-page);
		padding: 0.125rem 0.75rem;
		border-bottom: 1px solid var(--color-border);
		border-right: 1px solid var(--color-border);
		transition: background-color 0.1s;
	}
	.species-cell {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
	}
	.group-badge {
		flex-shrink: 0;
		height: 1.25rem;
		min-width: 1.5rem;
		padding: 0 0.25rem;
		border-radius: 0.25rem;
		font-size: 0.625rem;
		font-weight: 700;
		display: flex;
		align-items: center;
		justify-content: center;
		color: #fff;
		line-height: 1;
	}
	.bocc-dot-sm {
		flex-shrink: 0;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 9999px;
	}
	.species-link-wrap {
		font-size: 0.75rem;
		color: var(--color-text-3);
	}
	.species-link {
		color: inherit;
		text-decoration: none;
	}
	.species-link:hover {
		color: var(--color-accent-text);
		text-decoration: underline;
	}
	.status-badge {
		flex-shrink: 0;
		font-size: 0.5625rem;
		font-weight: 600;
		padding: 0 0.25rem;
		border-radius: 0.25rem;
		line-height: 1rem;
	}

	.td-hour {
		width: 2rem;
		height: 1.75rem;
		text-align: center;
		border-bottom: 1px solid color-mix(in srgb, var(--color-border) 50%, transparent);
		transition: background-color 0.1s;
	}
	.hour-count {
		font-size: 0.625rem;
		line-height: 1;
		user-select: none;
		color: #e2e8f0;
	}
	/* Switch to dark text on the lightest (high-intensity) cyan cells */
	.hour-count.light-text { color: #0f172a; }

	.td-total {
		width: 3rem;
		text-align: right;
		padding: 0.125rem 0.75rem 0.125rem 0;
		border-bottom: 1px solid var(--color-border);
		border-left: 1px solid var(--color-border);
		font-size: 0.75rem;
		color: var(--color-text-3);
		font-weight: 500;
	}

	.hm-legend {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 1rem;
		border-top: 1px solid var(--color-border);
		background: color-mix(in srgb, var(--color-surface) 50%, transparent);
		flex-shrink: 0;
	}
	.legend-label {
		font-size: 0.625rem;
		color: var(--color-text-ghost);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.legend-swatch {
		width: 0.75rem;
		height: 0.75rem;
		border-radius: 0.125rem;
		border: 1px solid color-mix(in srgb, var(--color-border-strong) 40%, transparent);
	}
	.legend-note {
		margin-left: auto;
		font-size: 0.625rem;
		color: var(--color-text-ghost);
	}
</style>
