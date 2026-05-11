<script lang="ts">
	import { page } from '$app/stores';
	import {
		getSpeciesDetail,
		getSpeciesDetections,
		speciesImageUrl,
		type SpeciesStats,
		type Detection,
	} from '$lib/api';
	import { BOCC_COLOR, SPECIES_STATUS_STYLE, groupBadgeColor } from '$lib/bto';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatDate, formatTime, formatFullDate } from '$lib/time';
	import StatCard from '../../../components/StatCard.svelte';
	import Spectrogram from '../../../components/Spectrogram.svelte';

	const PAGE_SIZE = 50;

	// Species name comes from the URL — SvelteKit decodes it automatically.
	const speciesName = $derived($page.params.name ?? '');

	// Derive back-link from the optional ?from= query param.
	const backHref  = $derived($page.url.searchParams.get('from') === 'dashboard' ? '/' : '/species');
	const backLabel = $derived($page.url.searchParams.get('from') === 'dashboard' ? 'Dashboard' : 'All species');
	// ── Stats ──────────────────────────────────────────────────────────────────
	let stats          = $state<SpeciesStats | null>(null);
	let statsLoading   = $state(true);
	let statsError     = $state<string | null>(null);
	let headerImgError = $state(false);

	// ── Detections list ────────────────────────────────────────────────────────
	let detections     = $state<Detection[]>([]);
	let total          = $state(0);
	let offset         = $state(0);
	let listLoading    = $state(true);
	let listError      = $state<string | null>(null);

	const totalPages  = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));
	const currentPage = $derived(Math.floor(offset / PAGE_SIZE) + 1);

	// ── Derived formatting ────────────────────────────────────────────────────
	const boccColor   = $derived(stats?.uk_bocc ? BOCC_COLOR[stats.uk_bocc] : null);
	const statusStyle = $derived(
		stats?.species_status ? SPECIES_STATUS_STYLE[stats.species_status] : null
	);
	const groupColor = $derived(groupBadgeColor(stats?.group_name));

	// ── Fetch stats ────────────────────────────────────────────────────────────
	$effect(() => {
		const name = speciesName;
		statsLoading = true;
		statsError = null;
		getSpeciesDetail(name)
			.then(s => { stats = s; statsLoading = false; })
			.catch(e => { statsError = (e as Error).message; statsLoading = false; });
	});

	// ── Fetch detections list ─────────────────────────────────────────────────
	$effect(() => {
		const name = speciesName;
		const off  = offset;
		listLoading = true;
		listError   = null;
		getSpeciesDetections(name, { limit: PAGE_SIZE, offset: off })
			.then(r => {
				if (speciesName === name && offset === off) {
					detections  = r.detections;
					total       = r.total;
					listLoading = false;
				}
			})
			.catch(e => {
				if (speciesName === name && offset === off) {
					listError   = (e as Error).message;
					listLoading = false;
				}
			});
	});

	function prevPage() { offset = Math.max(0, offset - PAGE_SIZE); }
	function nextPage() { offset = offset + PAGE_SIZE; }
</script>

<div class="h-[calc(100vh-3.25rem)] overflow-y-auto">
	<div class="max-w-5xl mx-auto px-6 py-5 space-y-6">

		<!-- Back button -->
		<a
			href={backHref}
			class="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
			       transition-colors"
		>
			<svg viewBox="0 0 16 16" class="w-3.5 h-3.5 fill-current" aria-hidden="true">
				<path d="M10.5 3L5.5 8l5 5" stroke="currentColor" stroke-width="1.5"
				      fill="none" stroke-linecap="round" stroke-linejoin="round"/>
			</svg>
			{backLabel}
		</a>

		<!-- ── Species header ─────────────────────────────────────────────────── -->
		<div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden">
			<!-- Banner image -->
			<div class="relative h-44 bg-slate-200 dark:bg-slate-800 overflow-hidden">
				{#if !headerImgError}
					<img
						src={speciesImageUrl(speciesName)}
						alt={speciesName}
						class="w-full h-full object-cover"
						onerror={() => (headerImgError = true)}
					/>
					<!-- Gradient overlay so text is readable -->
					<div class="absolute inset-0 bg-gradient-to-t from-slate-900/90 via-slate-900/30 to-transparent">
					</div>
				{:else}
					<!-- Fallback: group-coloured banner -->
					<div
						class="absolute inset-0 opacity-20"
						style="background-color: {groupColor}"
					></div>
					<div class="absolute inset-0 flex items-center justify-center">
						<svg viewBox="0 0 24 24" class="w-20 h-20 text-slate-300 dark:text-slate-700 fill-current" aria-hidden="true">
							<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
						</svg>
					</div>
				{/if}

				<!-- Badges pinned top-left over the image -->
				<div class="absolute top-3 left-3 flex items-center gap-1.5 flex-wrap">
					{#if stats?.group_name}
						<span
							class="h-5 px-2 rounded text-[10px] font-bold text-white flex items-center"
							style="background-color: {groupColor}"
						>
							{stats.group_name}
						</span>
					{/if}
					{#if boccColor && stats?.uk_bocc}
						<span
							class="h-5 px-2 rounded text-[10px] font-bold flex items-center"
							style="background-color: {boccColor}; color: #0f172a"
						>
							BoCC {stats.uk_bocc}
						</span>
					{/if}
					{#if statusStyle && stats?.species_status}
						<span
							class="h-5 px-2 rounded text-[10px] font-bold flex items-center"
							style="background-color: {statusStyle.bg}; color: {statusStyle.text}"
						>
							{stats.species_status}
						</span>
					{/if}
				</div>
			</div>

			<!-- Name row -->
			<div class="px-5 py-4">
				{#if statsLoading}
					<div class="h-7 bg-slate-200 dark:bg-slate-800 rounded animate-pulse w-48 mb-2"></div>
					<div class="h-4 bg-slate-200 dark:bg-slate-800 rounded animate-pulse w-32"></div>
				{:else if statsError}
					<p class="text-red-400 text-sm">{statsError}</p>
				{:else if stats}
					<h1 class="text-2xl font-bold text-slate-900 dark:text-slate-100 leading-tight">{stats.species}</h1>
					{#if stats.scientific_name}
						<p class="text-sm text-slate-500 italic mt-0.5">{stats.scientific_name}</p>
					{/if}
					{#if stats.bto_5letter_code || stats.bto_2letter_code}
						<p class="text-xs text-slate-400 dark:text-slate-600 font-mono mt-1">
							BTO {[stats.bto_5letter_code, stats.bto_2letter_code].filter(Boolean).join(' / ')}
						</p>
					{/if}
				{/if}
			</div>
		</div>

		<!-- ── Stat cards ─────────────────────────────────────────────────────── -->
		<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
			<StatCard
				title="Total detections"
				value={stats ? stats.detections.toLocaleString() : null}
				loading={statsLoading}
			/>
			<StatCard
				title="Avg confidence"
				value={stats ? formatConfidence(stats.avg_confidence) : null}
				loading={statsLoading}
			/>
			<StatCard
				title="Peak confidence"
				value={stats ? formatConfidence(stats.peak_confidence) : null}
				loading={statsLoading}
			/>
			<StatCard
				title="First detected"
				value={stats ? formatFullDate(stats.first_detected) : null}
				loading={statsLoading}
			/>
			<StatCard
				title="Last detected"
				value={stats ? formatFullDate(stats.last_detected) : null}
				loading={statsLoading}
			/>
		</div>

		<!-- ── Recordings ─────────────────────────────────────────────────────── -->
		<div class="space-y-2">
			<div class="flex items-center justify-between">
				<h2 class="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-widest">
					Recordings
				</h2>
				{#if !listLoading && total > 0}
					<span class="text-xs text-slate-500 tabular-nums">
						{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
					</span>
				{/if}
			</div>

			{#if listLoading}
				<div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg divide-y divide-slate-200 dark:divide-slate-800">
					{#each Array(8) as _}
						<div class="flex gap-3 px-4 py-3">
							<div class="w-1 h-12 bg-slate-200 dark:bg-slate-800 rounded animate-pulse shrink-0"></div>
							<div class="flex-1 space-y-2">
								<div class="flex justify-between">
									<div class="h-4 bg-slate-200 dark:bg-slate-800 rounded animate-pulse w-24"></div>
									<div class="h-4 bg-slate-200 dark:bg-slate-800 rounded animate-pulse w-16"></div>
								</div>
								<div class="h-12 bg-slate-200 dark:bg-slate-800 rounded animate-pulse"></div>
								<div class="h-8 bg-slate-200 dark:bg-slate-800 rounded animate-pulse"></div>
							</div>
						</div>
					{/each}
				</div>
			{:else if listError}
				<div class="text-sm text-red-400 py-4">{listError}</div>
			{:else if detections.length === 0}
				<div class="text-sm text-slate-500 py-8 text-center">No recordings found.</div>
			{:else}
				<div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg divide-y divide-slate-200 dark:divide-slate-800">
					{#each detections as det (det.id)}
						{@const isNotable = det.uk_bocc === 'Red' || det.species_status === 'Rare' || det.species_status === 'Very rare'}
						{@const badgeClass = confidenceBadgeClass(det.confidence)}
						<div
							class="flex gap-3 px-4 py-3 transition-colors
							       {isNotable ? 'border-l-2 border-l-red-500 bg-red-50/50 dark:bg-red-950/10' : 'hover:bg-slate-100 dark:hover:bg-slate-800/40'}"
						>
							<!-- Confidence bar -->
							<div class="flex flex-col items-center gap-1 pt-0.5 shrink-0">
								<div
									class="w-1 rounded-full bg-slate-300 dark:bg-slate-700 relative overflow-hidden"
									style="height: 48px"
									aria-label="Confidence {formatConfidence(det.confidence)}"
								>
									<div
										class="absolute bottom-0 left-0 right-0 rounded-full
										       {isNotable ? 'bg-red-500' : 'bg-emerald-500'}"
										style="height: {det.confidence * 100}%"
									></div>
								</div>
							</div>

							<!-- Content -->
							<div class="flex-1 min-w-0">
								<div class="flex items-center justify-between gap-2 mb-1.5">
									<div class="flex items-center gap-2 flex-wrap">
										<time
											class="text-sm font-semibold text-slate-800 dark:text-slate-200 tabular-nums"
											datetime={det.timestamp}
										>
											{formatTime(det.timestamp)}
										</time>
										<span class="text-xs text-slate-500">
											{formatDate(det.timestamp)}
										</span>
										<span class="text-xs px-1.5 py-0.5 rounded-full font-mono {badgeClass}">
											{formatConfidence(det.confidence)}
										</span>
										{#if isNotable}
											<span
												class="text-[9px] font-bold px-1.5 py-px rounded"
												style="background-color: {BOCC_COLOR.Red}22; color: {BOCC_COLOR.Red}"
											>
												{det.uk_bocc === 'Red' ? 'Red List' : det.species_status === 'Very rare' ? 'Very rare' : 'Rare'}
											</span>
										{/if}
									</div>
								</div>
								<Spectrogram filename={det.filename} species={det.species} />
							</div>
						</div>
					{/each}
				</div>

				<!-- Pagination -->
				{#if total > PAGE_SIZE}
					<div class="flex items-center justify-center gap-4 py-2">
						<button
							class="px-3 py-1.5 rounded border border-slate-300 dark:border-slate-700 text-sm
							       text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200
							       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
							disabled={offset === 0}
							onclick={prevPage}
						>
							← Prev
						</button>
						<span class="text-xs text-slate-500 tabular-nums">
							Page {currentPage} of {totalPages}
						</span>
						<button
							class="px-3 py-1.5 rounded border border-slate-300 dark:border-slate-700 text-sm
							       text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200
							       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
							disabled={offset + PAGE_SIZE >= total}
							onclick={nextPage}
						>
							Next →
						</button>
					</div>
				{/if}
			{/if}
		</div>

	</div>
</div>
