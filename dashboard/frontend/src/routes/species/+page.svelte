<script lang="ts">
	import {
		getSpeciesList,
		SPECIES_PERIODS,
		SORT_OPTIONS,
		type SpeciesPeriod,
		type SortOption,
		type SpeciesStats
	} from '$lib/api';
	import SpeciesCard from '../../components/species/SpeciesCard.svelte';
	import SpeciesRow  from '../../components/species/SpeciesRow.svelte';

	const PAGE_SIZE = 24;

	let period   = $state<SpeciesPeriod>('all');
	let sort     = $state<SortOption>('detections_desc');
	let dateFrom = $state('');
	let dateTo   = $state('');
	let offset   = $state(0);
	let view     = $state<'card' | 'list'>('card');

	let total       = $state(0);
	let speciesList = $state<SpeciesStats[]>([]);
	let loading     = $state(true);
	let error       = $state<string | null>(null);

	function setPeriod(p: SpeciesPeriod) { period = p; offset = 0; }
	function setSort(s: SortOption)      { sort = s;   offset = 0; }

	const totalPages  = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));
	const currentPage = $derived(Math.floor(offset / PAGE_SIZE) + 1);
	const showFrom    = $derived(total === 0 ? 0 : offset + 1);
	const showTo      = $derived(Math.min(offset + PAGE_SIZE, total));

	$effect(() => {
		const p   = period;
		const s   = sort;
		const off = offset;
		const df  = p === 'custom' ? dateFrom : '';
		const dt  = p === 'custom' ? dateTo   : '';

		loading = true;
		error   = null;

		getSpeciesList({
			period:    p,
			sort:      s,
			date_from: df || undefined,
			date_to:   dt || undefined,
			limit:     PAGE_SIZE,
			offset:    off
		})
			.then(r => {
				if (period === p && sort === s && offset === off) {
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
	<div class="max-w-7xl mx-auto px-6 py-5 space-y-5">

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
						<!-- Grid icon -->
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
						<!-- List icon -->
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

		<!-- Result count -->
		<div class="text-xs text-slate-500 h-4">
			{#if loading}
				Loading…
			{:else if error}
				<span class="text-red-400">{error}</span>
			{:else if total === 0}
				No species found for this period.
			{:else}
				Showing {showFrom}–{showTo} of {total} species
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
			{#if view === 'card'}
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
			<div class="text-center text-slate-500 py-16">No species recorded in this period.</div>
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
