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
	import SpeciesCard from '$lib/components/species/SpeciesCard.svelte';
	import SpeciesRow  from '$lib/components/species/SpeciesRow.svelte';

	const PAGE_SIZE = 24;

	let period      = $state<SpeciesPeriod>('all');
	let sort        = $state<SortOption>('detections_desc');
	let dateFrom    = $state('');
	let dateTo      = $state('');
	let offset      = $state(0);
	let view        = $state<'card' | 'list'>('card');

	let boccFilter   = $state('');
	let statusFilter = $state('');
	let groupFilter  = $state('');

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

	const GROUP_NAMES = Object.keys(GROUP_BADGE_COLORS).sort();

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

<div class="page-scroll">
	<div class="page-inner">

		<!-- Header + controls -->
		<div class="page-header">
			<h1 class="page-title">Species</h1>

			<div class="controls-row">
				<select
					class="select-input"
					value={sort}
					onchange={e => setSort(e.currentTarget.value as SortOption)}
				>
					{#each SORT_OPTIONS as opt}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>

				<select
					class="select-input"
					value={period}
					onchange={e => setPeriod(e.currentTarget.value as SpeciesPeriod)}
				>
					{#each SPECIES_PERIODS as p}
						<option value={p.value}>{p.label}</option>
					{/each}
				</select>

				<div class="view-toggle">
					<button
						title="Card view"
						aria-label="Card view"
						aria-pressed={view === 'card'}
						class="view-btn"
						class:active={view === 'card'}
						onclick={() => (view = 'card')}
					>
						<svg viewBox="0 0 16 16" class="view-icon" aria-hidden="true">
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
						class="view-btn"
						class:active={view === 'list'}
						onclick={() => (view = 'list')}
					>
						<svg viewBox="0 0 16 16" class="view-icon" aria-hidden="true">
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
			<div class="date-row">
				<span class="filter-label">From</span>
				<input
					type="date"
					bind:value={dateFrom}
					onchange={() => { offset = 0; }}
					class="date-input"
				/>
				<span class="filter-label">to</span>
				<input
					type="date"
					bind:value={dateTo}
					onchange={() => { offset = 0; }}
					class="date-input"
				/>
			</div>
		{/if}

		<!-- Conservation filters row -->
		<div class="filter-row">
			<!-- BoCC filter -->
			<div class="filter-group">
				<span class="filter-label">BoCC</span>
				{#each [['', 'All'], ['Red', 'Red'], ['Amber', 'Amber'], ['Green', 'Green']] as [val, label]}
					{@const color = val ? BOCC_COLOR[val as string] : null}
					<button
						class="filter-btn"
						class:active={boccFilter === val}
						style={boccFilter === val && color ? `border-color: ${color}; color: ${color}` : ''}
						onclick={() => setBocc(val as string)}
						aria-pressed={boccFilter === val}
					>
						{#if color}
							<span class="dot" style="background-color: {color}"></span>
						{/if}
						{label}
					</button>
				{/each}
			</div>

			<!-- Status filter -->
			<div class="filter-group">
				<span class="filter-label">Status</span>
				{#each [['', 'All'], ['Common', 'Common'], ['Scarce', 'Scarce'], ['Rare', 'Rare'], ['Very rare', 'V.rare']] as [val, label]}
					{@const style = val ? SPECIES_STATUS_STYLE[val as string] : null}
					<button
						class="filter-btn"
						class:active={statusFilter === val}
						style={statusFilter === val && style ? `border-color: ${style.text}; color: ${style.text}` : ''}
						onclick={() => setStatus(val as string)}
						aria-pressed={statusFilter === val}
					>
						{label}
					</button>
				{/each}
			</div>

			<!-- Group filter -->
			<div class="filter-group">
				<span class="filter-label">Group</span>
				<select
					class="select-input select-sm"
					class:select-active={!!groupFilter}
					value={groupFilter}
					onchange={e => setGroup(e.currentTarget.value)}
				>
					<option value="">All groups</option>
					{#each GROUP_NAMES as g}
						<option value={g}>{g}</option>
					{/each}
				</select>
			</div>

			{#if hasFilters}
				<button class="clear-btn" onclick={clearFilters}>Clear filters ✕</button>
			{/if}
		</div>

		<!-- Result count -->
		<div class="result-count">
			{#if loading}
				Loading…
			{:else if error}
				<span class="error-text">{error}</span>
			{:else if total === 0}
				No species found for this period{hasFilters ? ' with these filters' : ''}.
			{:else}
				Showing {showFrom}–{showTo} of {total} species{hasFilters ? ' (filtered)' : ''}
			{/if}
		</div>

		<!-- Species content -->
		{#if loading}
			{#if view === 'card'}
				<div class="card-grid">
					{#each Array(10) as _}
						<div class="skel-card">
							<div class="skel-img skeleton-pulse"></div>
							<div class="skel-body">
								<div class="skel-line skeleton-pulse" style="width: 75%"></div>
								<div class="skel-line skel-line-lg skeleton-pulse" style="width: 50%"></div>
								<div class="skel-lines">
									<div class="skel-line skeleton-pulse"></div>
									<div class="skel-line skeleton-pulse"></div>
									<div class="skel-line skeleton-pulse"></div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="list-surface">
					{#each Array(10) as _}
						<div class="skel-row">
							<div class="skel-thumb skeleton-pulse"></div>
							<div class="skel-line flex-1 skeleton-pulse"></div>
							<div class="skel-line" style="width:4rem" class:skeleton-pulse={true}></div>
							<div class="skel-line hide-sm skeleton-pulse" style="width:4rem"></div>
							<div class="skel-line hide-md skeleton-pulse" style="width:6rem"></div>
							<div class="skel-line hide-md skeleton-pulse" style="width:6rem"></div>
						</div>
					{/each}
				</div>
			{/if}
		{:else if speciesList.length > 0}
			{#if isSortedByGroup}
				{#each groupedSections() as section (section.group)}
					<div class="group-section">
						<div class="group-header">
							<span
								class="group-badge"
								style="background-color: {groupBadgeColor(section.group)}"
							>
								{section.group}
							</span>
							<span class="group-meta">
								{section.items.length} species
								· {section.items.reduce((t, s) => t + s.detections, 0).toLocaleString()} detections
							</span>
							<div class="group-rule"></div>
						</div>

						{#if view === 'card'}
							<div class="card-grid">
								{#each section.items as sp (sp.species)}
									<SpeciesCard species={sp} />
								{/each}
							</div>
						{:else}
							<div class="list-surface">
								<div class="list-header">
									<div class="lh-thumb"></div>
									<div class="lh-name">Species</div>
									<div class="lh-det">Detections</div>
									<div class="lh-peak hide-sm">Peak</div>
									<div class="lh-date hide-md">First seen</div>
									<div class="lh-date hide-md">Last seen</div>
								</div>
								{#each section.items as sp (sp.species)}
									<SpeciesRow species={sp} />
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			{:else if view === 'card'}
				<div class="card-grid">
					{#each speciesList as sp (sp.species)}
						<SpeciesCard species={sp} />
					{/each}
				</div>
			{:else}
				<div class="list-surface">
					<div class="list-header">
						<div class="lh-thumb"></div>
						<div class="lh-name">Species</div>
						<div class="lh-det">Detections</div>
						<div class="lh-peak hide-sm">Peak</div>
						<div class="lh-date hide-md">First seen</div>
						<div class="lh-date hide-md">Last seen</div>
					</div>
					{#each speciesList as sp (sp.species)}
						<SpeciesRow species={sp} />
					{/each}
				</div>
			{/if}
		{:else if !error}
			<div class="empty-state">
				{hasFilters ? 'No species match these filters.' : 'No species recorded in this period.'}
				{#if hasFilters}
					<button class="clear-link" onclick={clearFilters}>Clear filters</button>
				{/if}
			</div>
		{/if}

		<!-- Pagination -->
		{#if total > PAGE_SIZE}
			<div class="pagination">
				<button
					class="page-btn"
					disabled={offset === 0}
					onclick={() => (offset = Math.max(0, offset - PAGE_SIZE))}
				>
					← Prev
				</button>
				<span class="page-info tabular">Page {currentPage} of {totalPages}</span>
				<button
					class="page-btn"
					disabled={offset + PAGE_SIZE >= total}
					onclick={() => (offset = offset + PAGE_SIZE)}
				>
					Next →
				</button>
			</div>
		{/if}

	</div>
</div>

<style>
	.page-scroll {
		height: calc(100vh - var(--header-height));
		overflow-y: auto;
	}

	.page-inner {
		max-width: 80rem;
		margin: 0 auto;
		padding: 1.25rem 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.page-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.page-title {
		margin: 0;
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--color-text);
		letter-spacing: -0.025em;
	}

	.controls-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
	}

	/* Inputs */
	.select-input {
		font-size: 0.75rem;
		background: var(--color-surface-2);
		border: 1px solid var(--color-border-strong);
		color: var(--color-text);
		border-radius: 0.25rem;
		padding: 0.375rem 0.625rem;
		cursor: pointer;
	}
	.select-input:focus {
		outline: none;
		box-shadow: 0 0 0 2px var(--color-accent-ring);
	}
	.select-sm {
		padding: 0.125rem 0.5rem;
	}
	.select-active {
		border-color: var(--color-accent-border);
		color: var(--color-accent-text);
	}

	/* View toggle */
	.view-toggle {
		display: flex;
		border-radius: 0.375rem;
		overflow: hidden;
		border: 1px solid var(--color-border-strong);
	}
	.view-btn {
		padding: 0.375rem;
		border: none;
		background: transparent;
		cursor: pointer;
		color: var(--color-text-dim);
		transition: color 0.15s, background-color 0.15s;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.view-btn:hover {
		color: var(--color-text-muted);
	}
	.view-btn.active {
		background: var(--color-accent);
		color: #fff;
	}
	.view-icon {
		width: 0.875rem;
		height: 0.875rem;
		fill: currentColor;
	}

	/* Date row */
	.date-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem;
		font-size: 0.75rem;
	}
	.date-input {
		font-size: 0.75rem;
		background: var(--color-surface-2);
		border: 1px solid var(--color-border-strong);
		color: var(--color-text);
		border-radius: 0.25rem;
		padding: 0.375rem 0.625rem;
	}
	.date-input:focus {
		outline: none;
		box-shadow: 0 0 0 2px var(--color-accent-ring);
	}

	/* Filter row */
	.filter-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem;
	}
	.filter-group {
		display: flex;
		align-items: center;
		gap: 0.25rem;
	}
	.filter-label {
		font-size: 0.625rem;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-right: 0.125rem;
	}
	.filter-btn {
		font-size: 0.625rem;
		padding: 0.125rem 0.5rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-border);
		background: transparent;
		cursor: pointer;
		color: var(--color-text-muted);
		font-weight: 500;
		transition: color 0.15s, border-color 0.15s, background-color 0.15s;
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
	}
	.filter-btn:hover {
		color: var(--color-text);
		border-color: var(--color-border-strong);
	}
	.filter-btn.active {
		background: var(--color-surface-2);
		border-color: var(--color-border-strong);
		color: var(--color-text);
	}
	.dot {
		display: inline-block;
		width: 0.375rem;
		height: 0.375rem;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.clear-btn {
		font-size: 0.625rem;
		padding: 0.125rem 0.5rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		cursor: pointer;
		color: var(--color-text-muted);
		transition: color 0.15s, border-color 0.15s;
	}
	.clear-btn:hover {
		color: var(--color-text);
		border-color: var(--color-border-strong);
	}

	/* Result count */
	.result-count {
		font-size: 0.75rem;
		color: var(--color-text-muted);
		height: 1rem;
	}
	.error-text {
		color: #f87171;
	}

	/* Skeletons */
	.skel-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}
	.skel-img {
		aspect-ratio: 16 / 9;
		background: var(--color-skeleton);
	}
	.skel-body {
		padding: 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.skel-line {
		height: 0.875rem;
		background: var(--color-skeleton);
		border-radius: 0.25rem;
	}
	.skel-line-lg {
		height: 1.25rem;
	}
	.skel-lines {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		padding-top: 0.25rem;
	}
	.skel-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.625rem 0.75rem;
		border-bottom: 1px solid var(--color-border);
	}
	.skel-thumb {
		width: 2.75rem;
		height: 2.75rem;
		border-radius: 0.25rem;
		background: var(--color-skeleton);
		flex-shrink: 0;
	}

	/* Card grid */
	.card-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1rem;
	}
	@media (min-width: 768px)  { .card-grid { grid-template-columns: repeat(3, 1fr); } }
	@media (min-width: 1024px) { .card-grid { grid-template-columns: repeat(4, 1fr); } }
	@media (min-width: 1280px) { .card-grid { grid-template-columns: repeat(5, 1fr); } }

	/* List surface */
	.list-surface {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}
	.list-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid var(--color-border-strong);
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.lh-thumb { width: 2.75rem; flex-shrink: 0; }
	.lh-name  { flex: 1; }
	.lh-det   { width: 6rem; text-align: right; flex-shrink: 0; }
	.lh-peak  { width: 4rem; text-align: right; flex-shrink: 0; }
	.lh-date  { width: 7rem; text-align: right; flex-shrink: 0; }

	/* Group sections */
	.group-section {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.group-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding-top: 0.25rem;
	}
	.group-badge {
		height: 1.25rem;
		padding: 0 0.5rem;
		border-radius: 0.25rem;
		font-size: 0.625rem;
		font-weight: 700;
		color: #fff;
		display: inline-flex;
		align-items: center;
	}
	.group-meta {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}
	.group-rule {
		flex: 1;
		height: 1px;
		background: var(--color-border-strong);
	}

	/* Empty state */
	.empty-state {
		text-align: center;
		color: var(--color-text-muted);
		padding: 4rem 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
	}
	.clear-link {
		font-size: 0.75rem;
		color: var(--color-accent-text);
		text-decoration: underline;
		background: none;
		border: none;
		cursor: pointer;
	}
	.clear-link:hover {
		color: var(--color-accent);
	}

	/* Pagination */
	.pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		padding: 0.5rem 0;
	}
	.page-btn {
		padding: 0.375rem 0.75rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		cursor: pointer;
		font-size: 0.875rem;
		color: var(--color-text-muted);
		transition: color 0.15s, border-color 0.15s;
	}
	.page-btn:hover:not(:disabled) {
		color: var(--color-text);
		border-color: var(--color-border-strong);
	}
	.page-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.page-info {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}

	/* Responsive hide helpers */
	@media (max-width: 639px)  { .hide-sm { display: none; } }
	@media (max-width: 767px)  { .hide-md { display: none; } }
</style>
