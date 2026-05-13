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
	import StatCard from '$lib/components/StatCard.svelte';
	import Spectrogram from '$lib/components/Spectrogram.svelte';

	const PAGE_SIZE = 50;

	const speciesName = $derived($page.params.name ?? '');
	const backHref    = $derived($page.url.searchParams.get('from') === 'dashboard' ? '/' : '/species');
	const backLabel   = $derived($page.url.searchParams.get('from') === 'dashboard' ? 'Dashboard' : 'All species');

	let stats          = $state<SpeciesStats | null>(null);
	let statsLoading   = $state(true);
	let statsError     = $state<string | null>(null);
	let headerImgError = $state(false);

	let detections     = $state<Detection[]>([]);
	let total          = $state(0);
	let offset         = $state(0);
	let listLoading    = $state(true);
	let listError      = $state<string | null>(null);

	const totalPages  = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));
	const currentPage = $derived(Math.floor(offset / PAGE_SIZE) + 1);

	const boccColor   = $derived(stats?.uk_bocc ? BOCC_COLOR[stats.uk_bocc] : null);
	const statusStyle = $derived(
		stats?.species_status ? SPECIES_STATUS_STYLE[stats.species_status] : null
	);
	const groupColor = $derived(groupBadgeColor(stats?.group_name));

	$effect(() => {
		const name = speciesName;
		statsLoading = true;
		statsError = null;
		getSpeciesDetail(name)
			.then(s => { stats = s; statsLoading = false; })
			.catch(e => { statsError = (e as Error).message; statsLoading = false; });
	});

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

<div class="page-scroll">
	<div class="page-inner">

		<!-- Back button -->
		<a href={backHref} class="back-link">
			<svg viewBox="0 0 16 16" class="back-icon" aria-hidden="true">
				<path d="M10.5 3L5.5 8l5 5" stroke="currentColor" stroke-width="1.5"
				      fill="none" stroke-linecap="round" stroke-linejoin="round"/>
			</svg>
			{backLabel}
		</a>

		<!-- Species header card -->
		<div class="header-card">
			<!-- Banner image -->
			<div class="banner">
				{#if !headerImgError}
					<img
						src={speciesImageUrl(speciesName)}
						alt={speciesName}
						class="banner-img"
						onerror={() => (headerImgError = true)}
					/>
					<div class="banner-gradient"></div>
				{:else}
					<div class="banner-fallback" style="background-color: {groupColor}"></div>
					<div class="banner-fallback-icon">
						<svg viewBox="0 0 24 24" class="bird-icon" aria-hidden="true">
							<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
						</svg>
					</div>
				{/if}

				<!-- Badges over image -->
				<div class="banner-badges">
					{#if stats?.group_name}
						<span class="badge" style="background-color: {groupColor}; color: #fff">
							{stats.group_name}
						</span>
					{/if}
					{#if boccColor && stats?.uk_bocc}
						<span class="badge" style="background-color: {boccColor}; color: #0f172a">
							BoCC {stats.uk_bocc}
						</span>
					{/if}
					{#if statusStyle && stats?.species_status}
						<span class="badge" style="background-color: {statusStyle.bg}; color: {statusStyle.text}">
							{stats.species_status}
						</span>
					{/if}
				</div>
			</div>

			<!-- Name row -->
			<div class="name-section">
				{#if statsLoading}
					<div class="skel skel-h7 skeleton-pulse" style="width:12rem"></div>
					<div class="skel skel-h4 skeleton-pulse" style="width:8rem;margin-top:.5rem"></div>
				{:else if statsError}
					<p class="error-text">{statsError}</p>
				{:else if stats}
					<h1 class="species-h1">{stats.species}</h1>
					{#if stats.scientific_name}
						<p class="sci-name">{stats.scientific_name}</p>
					{/if}
					{#if stats.bto_5letter_code || stats.bto_2letter_code}
						<p class="bto-code">
							BTO {[stats.bto_5letter_code, stats.bto_2letter_code].filter(Boolean).join(' / ')}
						</p>
					{/if}
				{/if}
			</div>
		</div>

		<!-- Stat cards -->
		<div class="stats-grid">
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

		<!-- Recordings section -->
		<div class="recordings">
			<div class="recordings-header">
				<h2 class="recordings-title">Recordings</h2>
				{#if !listLoading && total > 0}
					<span class="recordings-count tabular">
						{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
					</span>
				{/if}
			</div>

			{#if listLoading}
				<div class="det-surface">
					{#each Array(8) as _}
						<div class="det-skel-row">
							<div class="det-bar-skel skeleton-pulse"></div>
							<div class="det-skel-body">
								<div class="det-skel-top">
									<div class="skel skel-h4 skeleton-pulse" style="width:6rem"></div>
									<div class="skel skel-h4 skeleton-pulse" style="width:4rem"></div>
								</div>
								<div class="skel skel-h12 skeleton-pulse"></div>
								<div class="skel skel-h8 skeleton-pulse"></div>
							</div>
						</div>
					{/each}
				</div>
			{:else if listError}
				<div class="error-text">{listError}</div>
			{:else if detections.length === 0}
				<div class="empty-det">No recordings found.</div>
			{:else}
				<div class="det-surface">
				{#each detections as det (det.id)}
					{@const isNotable   = det.uk_bocc === 'Red' || det.species_status === 'Rare' || det.species_status === 'Very rare'}
					{@const isFlagged   = det.flagged === 1}
					{@const cvRan       = det.cross_validated === 1}
					{@const cvAgreed    = cvRan && det.cv_agree === 1}
					{@const cvDisagreed = cvRan && det.cv_agree === 0}
					{@const badgeClass  = confidenceBadgeClass(det.confidence)}
					<div
						class="det-row"
						class:det-notable={isNotable}
						class:det-flagged={isFlagged && !isNotable}
						class:det-normal={!isNotable && !isFlagged}
					>
						<!-- Confidence bar -->
						<div class="conf-bar-wrap">
							<div
								class="conf-bar-track"
								aria-label="Confidence {formatConfidence(det.confidence)}"
							>
								<div
									class="conf-bar-fill"
									class:conf-bar-notable={isNotable}
									class:conf-bar-flagged={isFlagged && !isNotable}
									style="height: {det.confidence * 100}%"
								></div>
							</div>
						</div>

						<!-- Content -->
						<div class="det-content">
							<div class="det-meta">
								<div class="det-meta-left">
									<time class="det-time tabular" datetime={det.timestamp}>
										{formatTime(det.timestamp)}
									</time>
									<span class="det-date">{formatDate(det.timestamp)}</span>
									<span class="{badgeClass}">{formatConfidence(det.confidence)}</span>
									{#if isNotable}
										<span
											class="notable-pill"
											style="background-color: {BOCC_COLOR.Red}22; color: {BOCC_COLOR.Red}"
										>
											{det.uk_bocc === 'Red' ? 'Red List' : det.species_status === 'Very rare' ? 'Very rare' : 'Rare'}
										</span>
									{/if}
									{#if isFlagged}
										<span class="micro-badge flagged-badge">Flagged</span>
									{:else if cvAgreed}
										<span class="micro-badge cv-agree-badge">CV ✓</span>
									{/if}
								</div>
							</div>
							<Spectrogram filename={det.filename} species={det.species} />
							{#if cvRan}
								<div class="cv-detail">
									<span>primary: <span class="tabular">{det.model ?? '—'}</span>
										{det.primary_confidence != null ? formatConfidence(det.primary_confidence) : ''}</span>
									{#if cvAgreed}
										<span class="cv-agree">
											{det.cv_secondary_model} agrees
											{det.cv_confidence != null ? formatConfidence(det.cv_confidence) : ''}
										</span>
									{:else if cvDisagreed}
										<span class="cv-disagree">
											{det.cv_secondary_model} → {det.cv_species ?? 'no match'}
											{det.cv_confidence != null ? formatConfidence(det.cv_confidence) : ''}
										</span>
									{/if}
								</div>
							{/if}
						</div>
					</div>
				{/each}
				</div>

				<!-- Pagination -->
				{#if total > PAGE_SIZE}
					<div class="pagination">
						<button class="page-btn" disabled={offset === 0} onclick={prevPage}>← Prev</button>
						<span class="page-info tabular">Page {currentPage} of {totalPages}</span>
						<button class="page-btn" disabled={offset + PAGE_SIZE >= total} onclick={nextPage}>Next →</button>
					</div>
				{/if}
			{/if}
		</div>

	</div>
</div>

<style>
	.page-scroll {
		height: calc(100vh - var(--header-height));
		overflow-y: auto;
	}

	.page-inner {
		max-width: 64rem;
		margin: 0 auto;
		padding: 1.25rem 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	/* Back link */
	.back-link {
		display: inline-flex;
		align-items: center;
		gap: 0.375rem;
		font-size: 0.75rem;
		color: var(--color-text-muted);
		text-decoration: none;
		transition: color 0.15s;
	}
	.back-link:hover { color: var(--color-text); }
	.back-icon {
		width: 0.875rem;
		height: 0.875rem;
	}

	/* Header card */
	.header-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}

	.banner {
		position: relative;
		height: 11rem;
		background: var(--color-skeleton);
		overflow: hidden;
	}
	.banner-img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.banner-gradient {
		position: absolute;
		inset: 0;
		background: linear-gradient(to top, rgba(15,23,42,0.9) 0%, rgba(15,23,42,0.3) 50%, transparent 100%);
	}
	.banner-fallback {
		position: absolute;
		inset: 0;
		opacity: 0.2;
	}
	.banner-fallback-icon {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.bird-icon {
		width: 5rem;
		height: 5rem;
		fill: currentColor;
		color: var(--color-text-ghost);
	}

	.banner-badges {
		position: absolute;
		top: 0.75rem;
		left: 0.75rem;
		display: flex;
		align-items: center;
		gap: 0.375rem;
		flex-wrap: wrap;
	}
	.badge {
		height: 1.25rem;
		padding: 0 0.5rem;
		border-radius: 0.25rem;
		font-size: 0.625rem;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
	}

	.name-section {
		padding: 1.25rem;
	}
	.species-h1 {
		margin: 0;
		font-size: 1.5rem;
		font-weight: 700;
		color: var(--color-text);
		line-height: 1.25;
	}
	.sci-name {
		margin: 0.25rem 0 0;
		font-size: 0.875rem;
		color: var(--color-text-muted);
		font-style: italic;
	}
	.bto-code {
		margin: 0.25rem 0 0;
		font-size: 0.75rem;
		color: var(--color-text-dim);
		font-family: ui-monospace, 'Cascadia Code', monospace;
	}

	/* Stat cards grid */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 0.75rem;
	}
	@media (min-width: 640px)  { .stats-grid { grid-template-columns: repeat(3, 1fr); } }
	@media (min-width: 1024px) { .stats-grid { grid-template-columns: repeat(5, 1fr); } }

	/* Recordings */
	.recordings {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.recordings-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.recordings-title {
		margin: 0;
		font-size: 0.625rem;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}
	.recordings-count {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}

	/* Detection surface */
	.det-surface {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}

	/* Detection rows */
	.det-row {
		display: flex;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--color-border);
		transition: background-color 0.1s;
	}
	.det-row:last-child { border-bottom: none; }
	.det-normal:hover { background: var(--color-surface-2); }
	.det-notable {
		border-left: 2px solid #ef4444;
		background: rgba(239, 68, 68, 0.04);
	}
	.det-flagged {
		border-left: 2px solid #f59e0b;
		background: rgba(245, 158, 11, 0.03);
	}

	/* Confidence bar */
	.conf-bar-wrap {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.25rem;
		padding-top: 0.125rem;
		flex-shrink: 0;
	}
	.conf-bar-track {
		width: 0.25rem;
		height: 3rem;
		border-radius: 9999px;
		background: var(--color-skeleton);
		position: relative;
		overflow: hidden;
	}
	.conf-bar-fill {
		position: absolute;
		bottom: 0;
		left: 0;
		right: 0;
		border-radius: 9999px;
		background: var(--color-accent);
	}
	.conf-bar-notable { background: #ef4444; }
	.conf-bar-flagged { background: #f59e0b; }

	/* Detection content */
	.det-content {
		flex: 1;
		min-width: 0;
	}
	.det-meta {
		margin-bottom: 0.375rem;
	}
	.det-meta-left {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.det-time {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text-2);
	}
	.det-date {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}
	.notable-pill {
		font-size: 0.5625rem;
		font-weight: 700;
		padding: 0.0625rem 0.375rem;
		border-radius: 0.25rem;
	}

	/* Micro badges */
	.micro-badge {
		font-size: 0.5625rem;
		font-weight: 700;
		padding: 0.0625rem 0.375rem;
		border-radius: 0.25rem;
	}
	.flagged-badge {
		background: rgba(245, 158, 11, 0.15);
		color: #f59e0b;
	}
	.cv-agree-badge {
		background: rgba(16, 185, 129, 0.15);
		color: #10b981;
		font-weight: 500;
	}

	/* CV detail row */
	.cv-detail {
		margin-top: 0.375rem;
		font-size: 0.625rem;
		color: var(--color-text-dim);
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem 0.75rem;
	}
	.cv-agree    { color: #34d399; }
	.cv-disagree { color: #fbbf24; }

	/* Loading skeletons */
	.det-skel-row {
		display: flex;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--color-border);
	}
	.det-bar-skel {
		width: 0.25rem;
		height: 3rem;
		background: var(--color-skeleton);
		border-radius: 9999px;
		flex-shrink: 0;
		margin-top: 0.125rem;
	}
	.det-skel-body {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.det-skel-top {
		display: flex;
		justify-content: space-between;
	}
	.skel {
		background: var(--color-skeleton);
		border-radius: 0.25rem;
	}
	.skel-h4  { height: 1rem; }
	.skel-h7  { height: 1.75rem; }
	.skel-h8  { height: 2rem; }
	.skel-h12 { height: 3rem; }

	/* Empty / error */
	.error-text {
		font-size: 0.875rem;
		color: #f87171;
		padding: 1rem 0;
	}
	.empty-det {
		font-size: 0.875rem;
		color: var(--color-text-muted);
		text-align: center;
		padding: 2rem 0;
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
		transition: color 0.15s;
	}
	.page-btn:hover:not(:disabled) { color: var(--color-text); }
	.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
	.page-info {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}
</style>
