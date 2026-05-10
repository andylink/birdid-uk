<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getDailySpeciesSummary } from '$lib/api';
	import { createSSE } from '$lib/sse';
	import type { Detection, DailySpeciesSummary } from '$lib/api';
	import { localToday, localHour, formatTime } from '$lib/time';
	import { TIMEZONE } from '$lib/timezone';
	import {
		BOCC_COLOR,
		SPECIES_STATUS_STYLE,
		GROUP_BADGE_COLORS,
		groupBadgeColor,
		speciesInitials,
	} from '$lib/bto';

	// ── Props ─────────────────────────────────────────────────────────────────

	let { selectedDate = $bindable(todayStr()) }: { selectedDate?: string } = $props();

	// ── State ─────────────────────────────────────────────────────────────────

	let summaries = $state<DailySpeciesSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let sse: ReturnType<typeof createSSE> | null = null;
	let boccFilter = $state<string>('all'); // 'all' | 'Red' | 'Amber' | 'Green'

	// ── Constants ─────────────────────────────────────────────────────────────

	const HOURS = Array.from({ length: 24 }, (_, i) => i);

	// Dark-theme heatmap: empty → cyan scale (9 levels)
	const HEATMAP_COLORS = [
		'',          // 0: no override
		'#082f49',   // 1
		'#0c4a6e',   // 2
		'#075985',   // 3
		'#0369a1',   // 4
		'#0284c7',   // 5
		'#0ea5e9',   // 6
		'#38bdf8',   // 7
		'#7dd3fc',   // 8
		'#bae6fd',   // 9: brightest
	] as const;

	// ── Derived ───────────────────────────────────────────────────────────────

	const isToday = $derived(selectedDate === todayStr());

	const sortedSummaries = $derived(
		[...summaries].sort((a, b) => {
			if (b.count !== a.count) return b.count - a.count;
			return (b.latest_heard ?? '').localeCompare(a.latest_heard ?? '');
		})
	);

	// Apply BoCC filter on top of the sort
	const filteredSummaries = $derived(
		boccFilter === 'all'
			? sortedSummaries
			: sortedSummaries.filter(s => s.uk_bocc === boccFilter)
	);

	const maxHourlyCount = $derived(
		Math.max(1, ...summaries.flatMap((s) => s.hourly_counts))
	);

	// ── Helpers ───────────────────────────────────────────────────────────────

	function todayStr(): string {
		return localToday();
	}

	function formatDisplayDate(d: string): string {
		return new Date(d + 'T12:00:00').toLocaleDateString('en-GB', {
			weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
		});
	}

	function addDays(d: string, n: number): string {
		const date = new Date(d + 'T12:00:00');
		date.setDate(date.getDate() + n);
		return date.toISOString().slice(0, 10);
	}

	function getIntensity(count: number): number {
		if (count <= 0) return 0;
		return Math.min(9, Math.max(1, Math.ceil((count / maxHourlyCount) * 9)));
	}

	// ── Data loading ──────────────────────────────────────────────────────────

	async function fetchData(date: string) {
		loading = true;
		error = null;
		try {
			summaries = await getDailySpeciesSummary(date);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Could not load species data';
			summaries = [];
		} finally {
			loading = false;
		}
	}

	$effect(() => { void fetchData(selectedDate); });

	// ── Date navigation ───────────────────────────────────────────────────────

	function prevDay() { selectedDate = addDays(selectedDate, -1); }
	function nextDay() { if (!isToday) selectedDate = addDays(selectedDate, 1); }
	function goToToday() { selectedDate = todayStr(); }

	function handleDateInput(e: Event) {
		const val = (e.target as HTMLInputElement).value;
		if (val && val <= todayStr()) selectedDate = val;
	}

	// ── SSE: real-time heatmap updates for today ──────────────────────────────

	onMount(() => {
		sse = createSSE('/stream/detections');
		sse.on('detection', (raw) => {
			const d = raw as Detection;
			if (selectedDate !== todayStr()) return;
			const detectionDay = new Date(d.timestamp).toLocaleDateString('en-CA', {
				timeZone: TIMEZONE
			});
			if (detectionDay !== todayStr()) return;

			const hour = localHour(d.timestamp);
			const idx = summaries.findIndex((s) => s.species === d.species);

			if (idx >= 0) {
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
				const hc = new Array(24).fill(0);
				hc[hour] = 1;
				summaries = [
					{
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
					},
					...summaries,
				];
			}
		});
	});

	onDestroy(() => sse?.close());
</script>

<section class="flex flex-col h-full bg-slate-950 overflow-hidden" aria-label="Daily species heatmap">

	<!-- ── Header ────────────────────────────────────────────────────────────── -->
	<header class="flex items-center gap-3 px-4 py-2 border-b border-slate-800 bg-slate-900 shrink-0 flex-wrap gap-y-2">
		<h2 class="text-xs font-semibold text-slate-400 uppercase tracking-widest">
			Daily Species Summary
		</h2>

		{#if !loading && !error}
			<span class="text-sm text-slate-300 font-medium hidden sm:block">
				{formatDisplayDate(selectedDate)}
			</span>
			{#if summaries.length > 0}
				<span class="text-xs text-slate-600">
					{filteredSummaries.length}{boccFilter !== 'all' ? `/${summaries.length}` : ''} species
					· {filteredSummaries.reduce((t, s) => t + s.count, 0)} detections
				</span>
			{/if}
		{/if}

		<!-- BoCC filter toggle -->
		{#if !loading && !error && summaries.length > 0}
			<div class="flex items-center gap-1 ml-2">
				{#each [['all', 'All', ''], ['Red', 'Red', '#ef4444'], ['Amber', 'Amber', '#f59e0b'], ['Green', 'Green', '#22c55e']] as [val, label, color]}
					<button
						class="text-[10px] px-2 py-0.5 rounded border transition-colors font-medium
						       {boccFilter === val
						         ? 'bg-slate-700 border-slate-500 text-slate-100'
						         : 'border-slate-700 text-slate-500 hover:text-slate-300'}"
						style={boccFilter === val && color ? `border-color: ${color}; color: ${color}` : ''}
						onclick={() => boccFilter = val}
						aria-pressed={boccFilter === val}
					>
						{#if color}
							<span class="inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle"
							      style="background-color: {color}"></span>
						{/if}{label}
					</button>
				{/each}
			</div>
		{/if}

		<div class="ml-auto flex items-center gap-1.5">
			<button
				onclick={prevDay}
				class="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-700 transition-colors"
				aria-label="Previous day"
			>
				<svg viewBox="0 0 20 20" class="w-4 h-4 fill-current">
					<path d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z"/>
				</svg>
			</button>

			<input
				type="date"
				value={selectedDate}
				max={todayStr()}
				oninput={handleDateInput}
				class="text-xs bg-slate-800 border border-slate-700 text-slate-200 rounded px-2 py-1
				       cursor-pointer focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500"
				aria-label="Select date"
			/>

			<button
				onclick={nextDay}
				disabled={isToday}
				class="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-700 transition-colors
				       disabled:opacity-30 disabled:cursor-not-allowed"
				aria-label="Next day"
			>
				<svg viewBox="0 0 20 20" class="w-4 h-4 fill-current">
					<path d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"/>
				</svg>
			</button>

			{#if !isToday}
				<button
					onclick={goToToday}
					class="text-xs px-2.5 py-1 rounded bg-emerald-600/20 text-emerald-400
					       hover:bg-emerald-600/30 border border-emerald-600/30 transition-colors font-medium"
				>
					Today
				</button>
			{/if}
		</div>
	</header>

	<!-- ── Scrollable table ───────────────────────────────────────────────── -->
	<div class="flex-1 overflow-auto min-h-0">

		{#if loading}
			<div class="p-3 space-y-1" aria-busy="true" aria-label="Loading…">
				{#each Array.from({ length: 10 }) as _}
					<div class="flex gap-0.5 animate-pulse">
						<div class="h-7 w-44 bg-slate-800 rounded shrink-0"></div>
						{#each HOURS as _h}
							<div class="h-7 w-8 bg-slate-800/40 rounded-sm shrink-0"></div>
						{/each}
						<div class="h-7 w-12 bg-slate-800 rounded shrink-0"></div>
					</div>
				{/each}
			</div>

		{:else if error}
			<div class="flex flex-col items-center justify-center h-40 gap-2 text-slate-500">
				<svg viewBox="0 0 24 24" class="w-8 h-8 fill-current opacity-40" aria-hidden="true">
					<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
				</svg>
				<p class="text-sm">{error}</p>
			</div>

		{:else if summaries.length === 0}
			<div class="flex flex-col items-center justify-center h-40 gap-2 text-slate-600">
				<svg viewBox="0 0 24 24" class="w-8 h-8 fill-current opacity-40" aria-hidden="true">
					<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
				</svg>
				<p class="text-sm">No detections for {formatDisplayDate(selectedDate)}</p>
			</div>

		{:else if filteredSummaries.length === 0}
			<div class="flex flex-col items-center justify-center h-40 gap-2 text-slate-600">
				<p class="text-sm">No {boccFilter} list species detected today.</p>
				<button
					class="text-xs text-emerald-500 hover:text-emerald-400 underline"
					onclick={() => boccFilter = 'all'}
				>Show all species</button>
			</div>

		{:else}
			<table class="border-collapse min-w-max w-full" role="grid" aria-label="Species detection heatmap">
				<thead class="sticky top-0 z-10">
					<tr>
						<th
							scope="col"
							class="sticky left-0 z-20 bg-slate-900 px-3 py-1.5 text-left text-xs
							       font-medium text-slate-400 border-b border-r border-slate-800 min-w-[10rem]"
						>
							Species
						</th>
						{#each HOURS as hour}
							<th
								scope="col"
								class="w-8 min-w-[2rem] py-1.5 text-center text-[10px] font-mono
								       font-normal text-slate-500 border-b border-slate-800 bg-slate-900"
							>
								{hour.toString().padStart(2, '0')}
							</th>
						{/each}
						<th
							scope="col"
							class="w-12 min-w-[3rem] py-1.5 text-right pr-3 text-xs font-medium
							       text-slate-400 border-b border-l border-slate-800 bg-slate-900"
						>
							Total
						</th>
					</tr>
				</thead>

			<tbody>
				{#each filteredSummaries as item (item.species)}
					{@const statusStyle = item.species_status ? SPECIES_STATUS_STYLE[item.species_status] : null}
					<tr class="group hover:bg-slate-800/20 transition-colors">
						<td
							class="sticky left-0 z-10 bg-slate-950 group-hover:bg-slate-900/60
							       px-3 py-0.5 border-b border-r border-slate-800/50 transition-colors"
						>
						<div class="flex items-center gap-2 min-w-0">
							<span
								class="shrink-0 h-5 min-w-[1.5rem] px-1 rounded text-[10px] font-bold
								       flex items-center justify-center text-white leading-none"
								style="background-color: {groupBadgeColor(item.group_name)}"
								aria-hidden="true"
							>
								{speciesInitials(item.species, item.bto_5letter_code, item.bto_2letter_code)}
							</span>
							{#if item.uk_bocc}
								<span
									class="shrink-0 w-2 h-2 rounded-full"
									style="background-color: {BOCC_COLOR[item.uk_bocc] ?? '#94a3b8'}"
									title="UK BoCC: {item.uk_bocc}"
									aria-label="UK Birds of Conservation Concern: {item.uk_bocc}"
								></span>
							{/if}
							<span class="truncate text-xs text-slate-200" title={item.species}>
								<a
									href="/species/{encodeURIComponent(item.species)}?from=dashboard"
									class="hover:text-emerald-400 hover:underline transition-colors focus:outline-none
									       focus-visible:text-emerald-400 focus-visible:underline"
								>
									{item.species}
								</a>
							</span>
							{#if statusStyle}
								<span
									class="shrink-0 text-[9px] font-semibold px-1 rounded leading-4"
									style="background-color: {statusStyle.bg}; color: {statusStyle.text}"
									title="Species status: {item.species_status}"
								>
									{item.species_status}
								</span>
							{/if}
						</div>
						</td>

							{#each HOURS as hour}
								{@const count = item.hourly_counts[hour] ?? 0}
								{@const intensity = getIntensity(count)}
								<td
									class="w-8 h-7 text-center border-b border-slate-800/20 transition-colors"
									style={intensity > 0 ? `background-color: ${HEATMAP_COLORS[intensity]}` : ''}
									title={count > 0
										? `${count} detection${count !== 1 ? 's' : ''} at ${hour.toString().padStart(2, '0')}:00`
										: `${hour.toString().padStart(2, '0')}:00 — no detections`}
									role="gridcell"
									aria-label="{item.species} {hour.toString().padStart(2,'0')}:00 {count} detections"
								>
									{#if count > 0}
										<span
											class="text-[10px] tabular-nums leading-none select-none
											       {intensity >= 7 ? 'text-slate-900' : 'text-slate-100'}"
										>
											{count}
										</span>
									{/if}
								</td>
							{/each}

							<td class="w-12 text-right pr-3 py-0.5 border-b border-l border-slate-800/50
							           text-xs text-slate-300 tabular-nums font-medium">
								{item.count}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>

	<!-- ── Legend ─────────────────────────────────────────────────────────── -->
	{#if !loading && !error && summaries.length > 0}
		<div class="flex items-center gap-2 px-4 py-2 border-t border-slate-800 bg-slate-900/50 shrink-0">
			<span class="text-[10px] text-slate-600 uppercase tracking-wider">Less</span>
			{#each HEATMAP_COLORS.slice(1) as color, i}
				<div
					class="w-3 h-3 rounded-sm border border-slate-700/40"
					style="background-color: {color}"
					title="Intensity {i + 1}"
				></div>
			{/each}
			<span class="text-[10px] text-slate-600 uppercase tracking-wider">More</span>
			<span class="ml-auto text-[10px] text-slate-700">per hour, scaled to peak</span>
		</div>
	{/if}

</section>
