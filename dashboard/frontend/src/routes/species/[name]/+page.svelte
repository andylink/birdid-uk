<script lang="ts">
	import { page } from '$app/stores';
	import {
		getSpeciesDetail,
		getSpeciesDetections,
		getSpeciesSummary,
		speciesImageUrl,
		adminDeleteDetection,
		adminSetVerification,
		adminBulkDelete,
		type SpeciesStats,
		type SpeciesSummary,
		type Detection,
	} from '$lib/api';
	import { auth } from '$lib/auth';
	import { BOCC_COLOR, SPECIES_STATUS_STYLE, groupBadgeColor } from '$lib/bto';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatDate, formatTime, formatFullDate } from '$lib/time';
	import StatCard from '$lib/components/StatCard.svelte';
	import Spectrogram from '$lib/components/Spectrogram.svelte';

	const PAGE_SIZE = 50;

	const speciesName = $derived($page.params.name ?? '');
	// Derive back-navigation target from the 'from' query param set by callers.
	const backHref    = $derived($page.url.searchParams.get('from') === 'dashboard' ? '/' : '/species');
	const backLabel   = $derived($page.url.searchParams.get('from') === 'dashboard' ? 'Dashboard' : 'All species');

	let stats          = $state<SpeciesStats | null>(null);
	let statsLoading   = $state(true);
	let statsError     = $state<string | null>(null);
	let headerImgError = $state(false);

	let summary        = $state<SpeciesSummary | null>(null);

	let detections     = $state<Detection[]>([]);
	let total          = $state(0);
	let offset         = $state(0);
	let listLoading    = $state(true);
	let listError      = $state<string | null>(null);

	// null = show all; otherwise filter to this verification_status value
	let verificationFilter = $state<string | null>(null);

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

	// Non-blocking: fetch Wikipedia summary; silently ignored if unavailable.
	$effect(() => {
		const name = speciesName;
		summary = null;
		getSpeciesSummary(name).then(s => { if (speciesName === name) summary = s; });
	});

	// Stale-response guard: compare name+offset+filter at response time to discard
	// results from superseded requests.
	$effect(() => {
		const name = speciesName;
		const off  = offset;
		const vsf  = verificationFilter;
		listLoading = true;
		listError   = null;
		getSpeciesDetections(name, {
			limit: PAGE_SIZE,
			offset: off,
			...(vsf !== null ? { verification_status: vsf } : {}),
		})
			.then(r => {
				if (speciesName === name && offset === off && verificationFilter === vsf) {
					detections  = r.detections;
					total       = r.total;
					listLoading = false;
				}
			})
			.catch(e => {
				if (speciesName === name && offset === off && verificationFilter === vsf) {
					listError   = (e as Error).message;
					listLoading = false;
				}
			});
	});

	function prevPage() { offset = Math.max(0, offset - PAGE_SIZE); }
	function nextPage() { offset = offset + PAGE_SIZE; }

	// Set (or clear) the verification filter and reset to page 1.
	function setFilter(status: string | null) {
		verificationFilter = status;
		offset = 0;
		// Clear local overrides — they're no longer meaningful for the new result set.
		verificationOverrides = new Map();
	}

	// Admin: per-detection verification overrides (id → verification_status string)
	let verificationOverrides = $state<Map<number, string>>(new Map());
	let deletingId    = $state<number | null>(null);

	// Admin: bulk-delete state for this species
	let bulkConfirm  = $state(false);
	let bulkDeleting = $state(false);
	let bulkMsg      = $state<string | null>(null);

	function verificationStatusLocal(det: Detection): string {
		return verificationOverrides.has(det.id)
			? (verificationOverrides.get(det.id) as string)
			: (det.verification_status ?? 'unverified');
	}

	async function handleDeleteRow(id: number) {
		if (deletingId !== null) return;
		deletingId = id;
		try {
			await adminDeleteDetection(id);
			detections = detections.filter(d => d.id !== id);
			total = Math.max(0, total - 1);
		} finally {
			deletingId = null;
		}
	}

	async function handleSetVerificationRow(det: Detection, target: string) {
		try {
			const result = await adminSetVerification(det.id, target);
			const updated = new Map(verificationOverrides);
			updated.set(det.id, result.verification_status);
			verificationOverrides = updated;
			// If a filter is active and the new status no longer matches it, remove
			// the row from view immediately (same UX as deleting while filtered).
			if (verificationFilter !== null && result.verification_status !== verificationFilter) {
				detections = detections.filter(d => d.id !== det.id);
				total = Math.max(0, total - 1);
			}
		} catch {
			// Leave status unchanged on error
		}
	}

	async function handleBulkDelete() {
		bulkDeleting = true;
		bulkMsg = null;
		try {
			const r = await adminBulkDelete(speciesName);
			bulkMsg = `Deleted ${r.deleted_rows} detection${r.deleted_rows !== 1 ? 's' : ''} and ${r.deleted_files} clip file${r.deleted_files !== 1 ? 's' : ''}.`;
			detections = [];
			total = 0;
			bulkConfirm = false;
		} finally {
			bulkDeleting = false;
		}
	}
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

		<!-- Species header card: image left, details right -->
		<div class="header-card">
			<!-- Left: image -->
			<div class="header-img-col">
				{#if !headerImgError}
					<img
						src={speciesImageUrl(stats?.bto_name ?? speciesName)}
						alt={speciesName}
						class="header-img"
						onerror={() => (headerImgError = true)}
					/>
					{#if stats?.avicommons_attribution_url && stats?.avicommons_image_by}
						<a
							href={stats.avicommons_attribution_url}
							target="_blank"
							rel="noopener noreferrer"
							class="header-attribution"
						>
							© {stats.avicommons_image_by}{stats.avicommons_image_license ? ` / ${stats.avicommons_image_license}` : ''}
						</a>
					{/if}
				{:else}
					<div class="header-fallback" style="background-color: {groupColor}"></div>
					<div class="header-fallback-icon">
						<svg viewBox="0 0 24 24" class="bird-icon" aria-hidden="true">
							<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
						</svg>
					</div>
				{/if}
			</div>

			<!-- Right: details -->
			<div class="header-details">
				<!-- Badges -->
				<div class="header-badges">
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

				{#if statsLoading}
					<div class="skel skel-h7 skeleton-pulse" style="width:12rem"></div>
					<div class="skel skel-h4 skeleton-pulse" style="width:8rem;margin-top:.5rem"></div>
					<div class="skel skel-h4 skeleton-pulse" style="width:6rem;margin-top:.375rem"></div>
				{:else if statsError}
					<p class="error-text">{statsError}</p>
				{:else if stats}
					<h1 class="species-h1">{stats.bto_name ?? stats.species}</h1>
					{#if stats.scientific_name}
						<p class="sci-name">{stats.scientific_name}</p>
					{/if}
					{#if stats.bto_5letter_code || stats.bto_2letter_code}
						<p class="bto-code">
							BTO {[stats.bto_5letter_code, stats.bto_2letter_code].filter(Boolean).join(' / ')}
						</p>
					{/if}
					{#if stats.british_list_status || stats.population_estimate}
						<div class="species-extra">
							{#if stats.british_list_status}
								<div class="species-extra-row">
									<span class="extra-label">British list</span>
									<span class="extra-value">{stats.british_list_status}</span>
								</div>
							{/if}
							{#if stats.population_estimate}
								<div class="species-extra-row">
									<span class="extra-label">Population</span>
									<span class="extra-value">{stats.population_estimate}</span>
								</div>
							{/if}
						</div>
					{/if}
					{#if summary}
						<p class="wiki-summary">{summary.extract}</p>
						{#if summary.wikipedia_url}
							<a
								href={summary.wikipedia_url}
								target="_blank"
								rel="noopener noreferrer"
								class="wiki-link"
							>Source: Wikipedia</a>
						{/if}
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
				{#if $auth.authenticated && total > 0}
					{#if !bulkConfirm}
						<button class="bulk-delete-btn" onclick={() => { bulkConfirm = true; bulkMsg = null; }}>
							Delete all {total.toLocaleString()}
						</button>
					{:else}
						<span class="bulk-confirm-row">
							<span class="bulk-confirm-label">Delete all {total.toLocaleString()} detections?</span>
							<button class="bulk-confirm-yes" disabled={bulkDeleting} onclick={handleBulkDelete}>
								{bulkDeleting ? 'Deleting…' : 'Confirm'}
							</button>
							<button class="bulk-cancel-btn" onclick={() => (bulkConfirm = false)}>Cancel</button>
						</span>
					{/if}
				{/if}
			</div>

			<!-- Verification filter pills -->
			<div class="filter-row" role="group" aria-label="Filter by verification status">
				<button
					class="filter-pill"
					class:filter-active={verificationFilter === null}
					onclick={() => setFilter(null)}
				>All</button>
				<button
					class="filter-pill filter-pill-auto"
					class:filter-active={verificationFilter === 'auto'}
					onclick={() => setFilter('auto')}
				>Auto ✓</button>
				<button
					class="filter-pill filter-pill-cv"
					class:filter-active={verificationFilter === 'cv'}
					onclick={() => setFilter('cv')}
				>CV ✓</button>
				<button
					class="filter-pill filter-pill-human"
					class:filter-active={verificationFilter === 'human'}
					onclick={() => setFilter('human')}
				>Human ✓</button>
				<button
					class="filter-pill filter-pill-unverified"
					class:filter-active={verificationFilter === 'unverified'}
					onclick={() => setFilter('unverified')}
				>Unverified</button>
			</div>
			{#if bulkMsg}
				<p class="bulk-msg" role="status">{bulkMsg}</p>
			{/if}

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
					{@const isNotable    = det.uk_bocc === 'Red' || det.species_status === 'Rare' || det.species_status === 'Very rare'}
					{@const rowStatus    = verificationStatusLocal(det)}
					{@const rowHuman     = rowStatus === 'human'}
					{@const cvRan        = det.cross_validated === 1}
					{@const cvAgreed     = cvRan && det.cv_agree === 1}
					{@const cvDisagreed  = cvRan && det.cv_agree === 0}
					{@const badgeClass   = confidenceBadgeClass(det.confidence)}
					<div
						class="det-row"
					class:det-notable={isNotable}
					class:det-human={rowHuman && !isNotable}
					class:det-normal={!isNotable && !rowHuman}
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
							class:conf-bar-human={rowHuman && !isNotable}
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
									<!-- Verification status badge -->
									{#if rowHuman}
										<span class="micro-badge badge-human" title="Verified by a human">Human ✓</span>
									{:else if rowStatus === 'cv'}
										<span class="micro-badge badge-cv" title="Both models agreed on this species">CV ✓</span>
									{:else if rowStatus === 'auto'}
										<span class="micro-badge badge-auto" title="Auto-approved: confidence above threshold">Auto ✓</span>
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
						<!-- Admin controls: shown when logged in.
						     Verify   → mark as human-verified.
						     Unverify → reset to unverified (shown for auto, cv, human). -->
						{#if $auth.authenticated}
							<div class="row-admin-row">
								{#if rowStatus !== 'human'}
									<button
										class="row-admin-btn row-verify-btn"
										onclick={() => handleSetVerificationRow(det, 'human')}
										title="Mark as human-verified"
									>Verify</button>
								{/if}
									{#if rowStatus !== 'unverified'}
										<button
											class="row-admin-btn row-unverify-btn"
											onclick={() => handleSetVerificationRow(det, 'unverified')}
											title="Reset to unverified"
										>Unverify</button>
									{/if}
									<button
										class="row-admin-btn row-delete-btn"
										disabled={deletingId === det.id}
										onclick={() => handleDeleteRow(det.id)}
										title="Delete this detection and its audio clip"
									>
										{deletingId === det.id ? '…' : 'Delete'}
									</button>
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
		display: flex;
		flex-direction: column;
	}
	@media (min-width: 640px) {
		.header-card { flex-direction: row; }
	}

	/* Left: image column */
	.header-img-col {
		position: relative;
		overflow: hidden;
		background: var(--color-skeleton);
		height: 12rem;
		flex-shrink: 0;
	}
	@media (min-width: 640px) {
		.header-img-col {
			width: 42%;
			height: auto;
			min-height: 11rem;
		}
	}
	.header-img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.header-attribution {
		position: absolute;
		bottom: 0.375rem;
		right: 0.5rem;
		color: rgba(255, 255, 255, 0.65);
		font-size: 0.5625rem;
		text-decoration: none;
		line-height: 1;
		z-index: 2;
		transition: color 0.15s;
	}
	.header-attribution:hover { color: rgba(255, 255, 255, 0.95); }
	.header-fallback {
		position: absolute;
		inset: 0;
		opacity: 0.2;
	}
	.header-fallback-icon {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.bird-icon {
		width: 4rem;
		height: 4rem;
		fill: currentColor;
		color: var(--color-text-ghost);
	}

	/* Right: details column */
	.header-details {
		flex: 1;
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.header-badges {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem;
		margin-bottom: 0.375rem;
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
	.species-h1 {
		margin: 0;
		font-size: 1.5rem;
		font-weight: 700;
		color: var(--color-text);
		line-height: 1.25;
	}
	.sci-name {
		margin: 0;
		font-size: 0.875rem;
		color: var(--color-text-muted);
		font-style: italic;
	}
	.bto-code {
		margin: 0;
		font-size: 0.75rem;
		color: var(--color-text-dim);
		font-family: ui-monospace, 'Cascadia Code', monospace;
	}
	.species-extra {
		margin-top: 0.5rem;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		border-top: 1px solid var(--color-border);
		padding-top: 0.5rem;
	}
	.species-extra-row {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}
	.extra-label {
		font-size: 0.625rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-text-muted);
		min-width: 5rem;
		flex-shrink: 0;
	}
	.extra-value {
		font-size: 0.8125rem;
		color: var(--color-text);
	}
	.wiki-summary {
		margin: 0.625rem 0 0;
		font-size: 0.8125rem;
		color: var(--color-text-muted);
		line-height: 1.6;
		border-top: 1px solid var(--color-border);
		padding-top: 0.625rem;
	}
	.wiki-link {
		display: inline-block;
		margin-top: 0.25rem;
		font-size: 0.6875rem;
		color: var(--color-text-dim);
		text-decoration: none;
		transition: color 0.15s;
	}
	.wiki-link:hover { color: var(--color-text-muted); }

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

	/* Verification filter pills */
	.filter-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem;
	}
	.filter-pill {
		padding: 0.2rem 0.65rem;
		border-radius: 999px;
		font-size: 0.7rem;
		font-weight: 500;
		border: 1px solid var(--color-border);
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
		transition: background 0.15s, color 0.15s, border-color 0.15s;
	}
	.filter-pill:hover { background: var(--color-surface); color: var(--color-text); }
	.filter-pill.filter-active {
		border-color: currentColor;
		color: var(--color-text);
		background: var(--color-surface);
	}
	/* Colour accents when active, matching badge palette */
	.filter-pill-auto.filter-active  { color: #d97706; border-color: #d97706; background: rgba(217,119,6,0.08); }
	.filter-pill-cv.filter-active    { color: #16a34a; border-color: #16a34a; background: rgba(22,163,74,0.08); }
	.filter-pill-human.filter-active { color: #2563eb; border-color: #2563eb; background: rgba(37,99,235,0.08); }
	.filter-pill-unverified.filter-active { color: var(--color-text-muted); border-color: var(--color-border); }

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
	/* Blue left border for human-verified detections */
	.det-human {
		border-left: 2px solid #3b82f6;
		background: rgba(59, 130, 246, 0.03);
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
	.conf-bar-human   { background: #3b82f6; }

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
	/* Blue = human-verified by admin */
	.badge-human {
		background: rgba(59, 130, 246, 0.15);
		color: #3b82f6;
	}
	/* Green = both models agreed (cross-validation) */
	.badge-cv {
		background: rgba(16, 185, 129, 0.15);
		color: #10b981;
	}
	/* Amber = auto-approved by confidence threshold, no human review */
	.badge-auto {
		background: rgba(245, 158, 11, 0.15);
		color: #f59e0b;
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

	/* Bulk-delete controls in the recordings header */
	.bulk-delete-btn {
		margin-left: auto;
		padding: 0.25rem 0.625rem;
		border-radius: 0.25rem;
		border: 1px solid rgba(239, 68, 68, 0.4);
		background: transparent;
		color: #f87171;
		font-size: 0.6875rem;
		font-weight: 600;
		cursor: pointer;
		transition: background-color 0.15s;
	}
	.bulk-delete-btn:hover { background: rgba(239, 68, 68, 0.08); }

	.bulk-confirm-row {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.bulk-confirm-label {
		font-size: 0.6875rem;
		color: #fbbf24;
	}
	.bulk-confirm-yes {
		padding: 0.25rem 0.625rem;
		border-radius: 0.25rem;
		border: none;
		background: #ef4444;
		color: #fff;
		font-size: 0.6875rem;
		font-weight: 600;
		cursor: pointer;
	}
	.bulk-confirm-yes:disabled { opacity: 0.4; cursor: not-allowed; }
	.bulk-cancel-btn {
		padding: 0.25rem 0.625rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		color: var(--color-text-muted);
		font-size: 0.6875rem;
		cursor: pointer;
	}
	.bulk-msg {
		margin: 0;
		font-size: 0.8125rem;
		color: #34d399;
		background: rgba(52, 211, 153, 0.08);
		border: 1px solid rgba(52, 211, 153, 0.2);
		border-radius: 0.375rem;
		padding: 0.5rem 0.75rem;
	}

	/* Per-row admin buttons */
	.row-admin-row {
		display: flex;
		gap: 0.375rem;
		margin-top: 0.375rem;
	}
	.row-admin-btn {
		padding: 0.1875rem 0.5rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		font-size: 0.625rem;
		font-weight: 600;
		cursor: pointer;
		color: var(--color-text-muted);
		transition: background-color 0.15s, color 0.15s, border-color 0.15s;
	}
	.row-admin-btn:disabled { opacity: 0.4; cursor: not-allowed; }
	.row-verify-btn:hover {
		background: rgba(59, 130, 246, 0.12);
		color: #3b82f6;
		border-color: #3b82f6;
	}
	.row-unverify-btn:hover {
		background: rgba(245, 158, 11, 0.12);
		color: #f59e0b;
		border-color: #f59e0b;
	}
	.row-delete-btn:hover:not(:disabled) {
		background: rgba(239, 68, 68, 0.12);
		color: #ef4444;
		border-color: #ef4444;
	}
</style>
