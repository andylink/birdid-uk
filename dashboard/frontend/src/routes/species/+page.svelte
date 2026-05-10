<script lang="ts">
	import {
		getSpeciesList,
		SPECIES_PERIODS,
		SORT_OPTIONS,
		type SpeciesPeriod,
		type SortOption,
		type SpeciesStats
	} from '$lib/api';
	import { GROUP_BADGE_COLORS, BOCC_COLOR, SPECIES_STATUS_STYLE, groupBadgeColor } from '$lib/bto';
	import SpeciesCard from '../../components/species/SpeciesCard.svelte';
	import SpeciesRow  from '../../components/species/SpeciesRow.svelte';

	const PAGE_SIZE = 24;

	let period      = $state<SpeciesPeriod>('all');
	let sort        = $state<SortOption>('detections_desc');
	let dateFrom    = $state('');
	let dateTo      = $state('');
	let offset      = $state(0);
	let view        = $state<'card' | 'list'>('card');

	// Conservation filters
	let boccFilter   = $state('');    // '' | 'Red' | 'Amber' | 'Green'
	let statusFilter = $state('');    // '' | 'Common' | 'Scarce' | 'Rare' | 'Very rare'
	let groupFilter  = $state('');    // '' | group_name

	let total       = $state(0);
	let speciesList = $state<SpeciesStats[]>([]);
	let loading     = $state(true);
	let error       = $state<string | null>(null);

	function setPeriod(p: SpeciesPeriod) { period = p; offset = 0; }
	function setSort(s: SortOption)      { sort = s;   offset = 0; }
	function setBocc(v: string)          { boccFilter = v;   offset = 0; }
	function setStatus(v: string)        { statusFilter = v; offset = 0; }
	function setGroup(v: string)         { groupFilter = v;  offset = 0; }
	function clearFilters()              { boccFilter = ''; statusFilter = ''; groupFilter = ''; offset = 0; }

	const hasFilters = $derived(!!(boccFilter || statusFilter || groupFilter));

	const totalPages  = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));
	const currentPage = $derived(Math.floor(offset / PAGE_SIZE) + 1);
	const showFrom    = $derived(total === 0 ? 0 : offset + 1);
	const showTo      = $derived(Math.min(offset + PAGE_SIZE, total));

	// Sorted group names from bto.ts (for the group dropdown)
	const GROUP_NAMES = Object.keys(GROUP_BADGE_COLORS).sort();

	// When sorted by group, group the results into sections for card/list view
	const isSortedByGroup = $derived(sort === 'group_asc' || sort === 'group_desc');

	interface GroupedSection { group: string; items: SpeciesStats[] }
	const groupedSections = $derived((): GroupedSection[] => {
		if (!isSortedByGroup) return [];
		const sections: GroupedSection[] = [];
		for (const sp of speciesList) {
			const g = sp.group_name ?? 'Unknown';
			const last = sections[sections.length - 1];
			if (!last || last.group !== g) sections.push({ group: g, items: [sp] });
			else last.items.push(sp);
		}
		return sections;
	});

	$effect(() => {
		const p   = period;
		const s   = sort;
		const off = offset;
		const df  = p === 'custom' ? dateFrom : '';
		const dt  = p === 'custom' ? dateTo   : '';
		const bc  = boccFilter;
		const st  = statusFilter;
		const gr  = groupFilter;

		loading = true;
		error   = null;

		getSpeciesList({
			period:    p,
			sort:      s,
			date_from: df || undefined,
			date_to:   dt || undefined,
			limit:     PAGE_SIZE,
			offset:    off,
			bocc:      bc || undefined,
			status:    st || undefined,
			group:     gr || undefined,
		})
			.then(r => {
				if (period === p && sort === s && offset === off &&
				    boccFilter === bc && statusFilter === st && groupFilter === gr) {
					total       = r.total;
					speciesList = r.species;
					loading     = false;
				}
			})
			.catch(e => {
				if (period === p && sort === s && offset === off) {
					error   = (e as Error).message;
					loading = false;
				}
			});
	});
</script>

<div class="h-[calc(100vh-3.25rem)] overflow-y-auto">
	<div class="max-w-7xl mx-auto px-6 py-5 space-y-4">

		<!-- Header + controls -->
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="text-lg font-semibold text-slate-100 tracking-tight">Species</h1>

			<div class="flex flex-wrap items-center gap-2">
				<!-- Sort -->
				<select
					class="text-xs bg-slate-800 border border-slate-700 text-slate-200 rounded
					       px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-emerald-500"
					value={sort}
					onchange={e => setSort(e.currentTarget.value as SortOption)}
				>
					{#each SORT_OPTIONS as opt}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>

				<!-- Period -->
				<select
					class="text-xs bg-slate-800 border border-slate-700 text-slate-200 rounded
					       px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-emerald-500"
					value={period}
					onchange={e => setPeriod(e.currentTarget.value as SpeciesPeriod)}
				>
					{#each SPECIES_PERIODS as p}
						<option value={p.value}>{p.label}</option>
					{/each}
				</select>

				<!-- View toggle -->
				<div class="flex rounded overflow-hidden border border-slate-700">
					<button
						title="Card view"
						aria-label="Card view"
						aria-pressed={view === 'card'}
						class="p-1.5 transition-colors {view === 'card'
							? 'bg-emerald-600 text-white'
							: 'text-slate-400 hover:text-slate-200'}"
						onclick={() => (view = 'card')}
					>
						<svg viewBox="0 0 16 16" class="w-3.5 h-3.5 fill-current" aria-hidden="true">
							<rect x="1" y="1" width="6" height="6" rx="1"/>
							<rect x="9" y="1" width="6" height="6" rx="1"/>
							<rect x="1" y="9" width="6" height="6" rx="1"/>
							<rect x="9" y="9" width="6" height="6" rx="1"/>
						</svg>
					</button>
					<button
						title="List view"
						aria-label="List view"
						aria-pressed={view === 'list'}
						class="p-1.5 transition-colors {view === 'list'
							? 'bg-emerald-600 text-white'
							: 'text-slate-400 hover:text-slate-200'}"
						onclick={() => (view = 'list')}
					>
						<svg viewBox="0 0 16 16" class="w-3.5 h-3.5 fill-current" aria-hidden="true">
							<rect x="1" y="2" width="14" height="2" rx="1"/>
							<rect x="1" y="7" width="14" height="2" rx="1"/>
							<rect x="1" y="12" width="14" height="2" rx="1"/>
						</svg>
					</button>
				</div>
			</div>
		</div>

		<!-- Custom date pickers -->
		{#if period === 'custom'}
			<div class="flex flex-wrap items-center gap-3 text-xs">
				<span class="text-slate-400">From</span>
				<input
					type="date"
					bind:value={dateFrom}
					onchange={() => { offset = 0; }}
					class="bg-slate-800 border border-slate-700 text-slate-200 rounded
					       px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-emerald-500"
				/>
				<span class="text-slate-400">to</span>
				<input
					type="date"
					bind:value={dateTo}
					onchange={() => { offset = 0; }}
					class="bg-slate-800 border border-slate-700 text-slate-200 rounded
					       px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-emerald-500"
				/>
			</div>
		{/if}

		<!-- Conservation filters row -->
		<div class="flex flex-wrap items-center gap-3">
			<!-- BoCC filter -->
			<div class="flex items-center gap-1">
				<span class="text-[10px] text-slate-500 uppercase tracking-wider mr-0.5">BoCC</span>
				{#each [['', 'All'], ['Red', 'Red'], ['Amber', 'Amber'], ['Green', 'Green']] as [val, label]}
					{@const color = val ? BOCC_COLOR[val] : null}
					<button
						class="text-[10px] px-2 py-0.5 rounded border transition-colors font-medium
						       {boccFilter === val
						         ? 'bg-slate-700 border-slate-500 text-slate-100'
						         : 'border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-600'}"
						style={boccFilter === val && color ? `border-color: ${color}; color: ${color}` : ''}
						onclick={() => setBocc(val)}
						aria-pressed={boccFilter === val}
					>
						{#if color}
							<span class="inline-block w-1.5 h-1.5 rounded-full mr-0.5 align-middle"
							      style="background-color: {color}"></span>
						{/if}{label}
					</button>
				{/each}
			</div>

			<!-- Status filter -->
			<div class="flex items-center gap-1">
				<span class="text-[10px] text-slate-500 uppercase tracking-wider mr-0.5">Status</span>
				{#each [['', 'All'], ['Common', 'Common'], ['Scarce', 'Scarce'], ['Rare', 'Rare'], ['Very rare', 'V.rare']] as [val, label]}
					{@const style = val ? SPECIES_STATUS_STYLE[val] : null}
					<button
						class="text-[10px] px-2 py-0.5 rounded border transition-colors font-medium
						       {statusFilter === val
						         ? 'bg-slate-700 border-slate-500 text-slate-100'
						         : 'border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-600'}"
						style={statusFilter === val && style ? `border-color: ${style.text}; color: ${style.text}` : ''}
						onclick={() => setStatus(val)}
						aria-pressed={statusFilter === val}
					>
						{label}
					</button>
				{/each}
			</div>

			<!-- Group filter -->
			<div class="flex items-center gap-1.5">
				<span class="text-[10px] text-slate-500 uppercase tracking-wider">Group</span>
				<select
					class="text-xs bg-slate-800 border border-slate-700 text-slate-200 rounded
					       px-2 py-0.5 focus:outline-none focus:ring-1 focus:ring-emerald-500
					       {groupFilter ? 'border-emerald-600/60 text-emerald-300' : ''}"
					value={groupFilter}
					onchange={e => setGroup(e.currentTarget.value)}
				>
					<option value="">All groups</option>
					{#each GROUP_NAMES as g}
						<option value={g}>{g}</option>
					{/each}
				</select>
			</div>

			<!-- Clear filters -->
			{#if hasFilters}
				<button
					class="text-[10px] px-2 py-0.5 rounded border border-slate-700 text-slate-400
					       hover:text-slate-200 hover:border-slate-500 transition-colors"
					onclick={clearFilters}
				>
					Clear filters ✕
				</button>
			{/if}
		</div>

		<!-- Result count -->
		<div class="text-xs text-slate-500 h-4">
			{#if loading}
				Loading…
			{:else if error}
				<span class="text-red-400">{error}</span>
			{:else if total === 0}
				No species found for this period{hasFilters ? ' with these filters' : ''}.
			{:else}
				Showing {showFrom}–{showTo} of {total} species{hasFilters ? ' (filtered)' : ''}
			{/if}
		</div>

		<!-- Species content -->
		{#if loading}
			{#if view === 'card'}
				<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
					{#each Array(10) as _}
						<div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
							<div class="aspect-video bg-slate-800 animate-pulse"></div>
							<div class="p-3 space-y-2">
								<div class="h-4 bg-slate-800 rounded animate-pulse w-3/4"></div>
								<div class="h-5 bg-slate-800 rounded animate-pulse w-1/2"></div>
								<div class="space-y-1 pt-1">
									<div class="h-3 bg-slate-800 rounded animate-pulse"></div>
									<div class="h-3 bg-slate-800 rounded animate-pulse"></div>
									<div class="h-3 bg-slate-800 rounded animate-pulse"></div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
					{#each Array(10) as _}
						<div class="flex items-center gap-3 px-3 py-2.5 border-b border-slate-800">
							<div class="w-11 h-11 rounded bg-slate-800 animate-pulse shrink-0"></div>
							<div class="flex-1 h-4 bg-slate-800 rounded animate-pulse"></div>
							<div class="w-16 h-4 bg-slate-800 rounded animate-pulse"></div>
							<div class="w-16 h-4 bg-slate-800 rounded animate-pulse hidden sm:block"></div>
							<div class="w-24 h-4 bg-slate-800 rounded animate-pulse hidden md:block"></div>
							<div class="w-24 h-4 bg-slate-800 rounded animate-pulse hidden md:block"></div>
						</div>
					{/each}
				</div>
			{/if}
		{:else if speciesList.length > 0}
			{#if isSortedByGroup}
				<!-- Group section view -->
				{#each groupedSections() as section (section.group)}
					<div class="space-y-2">
						<!-- Group header -->
						<div class="flex items-center gap-2 pt-1">
							<span
								class="h-5 px-2 rounded text-[10px] font-bold text-white flex items-center"
								style="background-color: {groupBadgeColor(section.group)}"
							>
								{section.group}
							</span>
							<span class="text-xs text-slate-500">
								{section.items.length} species
								· {section.items.reduce((t, s) => t + s.detections, 0).toLocaleString()} detections
							</span>
							<div class="flex-1 h-px bg-slate-800"></div>
						</div>
						{#if view === 'card'}
							<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
								{#each section.items as sp (sp.species)}
									<SpeciesCard species={sp} />
								{/each}
							</div>
						{:else}
							<div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
								<div class="flex items-center gap-3 px-3 py-2 border-b border-slate-700
								            text-xs font-semibold text-slate-500 uppercase tracking-wider">
									<div class="w-11 shrink-0"></div>
									<div class="flex-1">Species</div>
									<div class="w-24 text-right">Detections</div>
									<div class="w-16 text-right hidden sm:block">Peak</div>
									<div class="w-28 text-right hidden md:block">First seen</div>
									<div class="w-28 text-right hidden md:block">Last seen</div>
								</div>
								{#each section.items as sp (sp.species)}
									<SpeciesRow species={sp} />
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			{:else if view === 'card'}
				<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
					{#each speciesList as sp (sp.species)}
						<SpeciesCard species={sp} />
					{/each}
				</div>
			{:else}
				<div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
					<!-- Column headers -->
					<div
						class="flex items-center gap-3 px-3 py-2 border-b border-slate-700
						       text-xs font-semibold text-slate-500 uppercase tracking-wider"
					>
						<div class="w-11 shrink-0"></div>
						<div class="flex-1">Species</div>
						<div class="w-24 text-right">Detections</div>
						<div class="w-16 text-right hidden sm:block">Peak</div>
						<div class="w-28 text-right hidden md:block">First seen</div>
						<div class="w-28 text-right hidden md:block">Last seen</div>
					</div>
					{#each speciesList as sp (sp.species)}
						<SpeciesRow species={sp} />
					{/each}
				</div>
			{/if}
		{:else if !error}
			<div class="text-center text-slate-500 py-16">
				{hasFilters ? 'No species match these filters.' : 'No species recorded in this period.'}
				{#if hasFilters}
					<button
						class="block mx-auto mt-2 text-xs text-emerald-500 hover:text-emerald-400 underline"
						onclick={clearFilters}
					>Clear filters</button>
				{/if}
			</div>
		{/if}

		<!-- Pagination -->
		{#if total > PAGE_SIZE}
			<div class="flex items-center justify-center gap-4 py-2">
				<button
					class="px-3 py-1.5 rounded border border-slate-700 text-sm text-slate-400
					       hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed
					       transition-colors"
					disabled={offset === 0}
					onclick={() => (offset = Math.max(0, offset - PAGE_SIZE))}
				>
					← Prev
				</button>
				<span class="text-xs text-slate-500 tabular-nums">
					Page {currentPage} of {totalPages}
				</span>
				<button
					class="px-3 py-1.5 rounded border border-slate-700 text-sm text-slate-400
					       hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed
					       transition-colors"
					disabled={offset + PAGE_SIZE >= total}
					onclick={() => (offset = offset + PAGE_SIZE)}
				>
					Next →
				</button>
			</div>
		{/if}

	</div>
</div>
