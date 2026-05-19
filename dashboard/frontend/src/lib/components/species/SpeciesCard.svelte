<script lang="ts">
	import type { SpeciesStats } from '$lib/api';
	import { speciesImageUrl } from '$lib/api';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatFullDate } from '$lib/time';
	import { BOCC_COLOR, SPECIES_STATUS_STYLE } from '$lib/bto';

	let { species }: { species: SpeciesStats } = $props();

	let imgError = $state(false);

	const avgBadge = $derived(confidenceBadgeClass(species.avg_confidence));
	const statusStyle = $derived(
		species.species_status ? SPECIES_STATUS_STYLE[species.species_status] : null
	);
</script>

<article class="card">
	<a
		href="/species/{encodeURIComponent(species.species)}?from=species"
		class="card-link"
		aria-label="View recordings for {species.species}"
	>
		<div class="img-wrap">
			{#if imgError}
				<div class="img-fallback">
					<svg viewBox="0 0 24 24" class="fallback-icon" aria-hidden="true">
						<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
					</svg>
				</div>
			{:else}
				<img
					src={speciesImageUrl(species.species)}
					alt={species.species}
					class="species-img"
					onerror={() => (imgError = true)}
					loading="lazy"
				/>
			{/if}

			<!-- BoCC badge overlaid on image; dark text (#0f172a) works on Red, Amber, and Green -->
			{#if species.uk_bocc}
				<span
					class="bocc-badge"
					style="background-color: {BOCC_COLOR[species.uk_bocc]}; color: #0f172a"
				>
					{species.uk_bocc}
				</span>
			{/if}
		</div>

		<div class="stats">
			<div class="name-row">
				<div class="name-col">
					<h3 class="common-name">{species.species}</h3>
					{#if species.scientific_name}
						<p class="sci-name truncate">{species.scientific_name}</p>
					{/if}
				</div>
				<span class="{avgBadge}">{formatConfidence(species.avg_confidence)}</span>
			</div>

			{#if statusStyle}
				<div class="badges">
					<span
						class="status-badge"
						style="background-color: {statusStyle.bg}; color: {statusStyle.text}"
					>
						{species.species_status}
					</span>
				</div>
			{/if}

			<div class="det-count">
				{species.detections.toLocaleString()}<span class="det-label">detections</span>
			</div>

			<!-- detail-list pushed to card bottom via margin-top: auto -->
			<dl class="detail-list">
				<div class="detail-row">
					<dt>Peak</dt>
					<dd class="tabular">{formatConfidence(species.peak_confidence)}</dd>
				</div>
				<div class="detail-row">
					<dt>First seen</dt>
					<dd>{formatFullDate(species.first_detected)}</dd>
				</div>
				<div class="detail-row">
					<dt>Last seen</dt>
					<dd>{formatFullDate(species.last_detected)}</dd>
				</div>
				{#if species.bto_5letter_code || species.bto_2letter_code}
					<div class="detail-row">
						<dt>BTO code</dt>
						<!-- Show both 2- and 5-letter BTO codes where available -->
						<dd class="tabular">
							{[species.bto_2letter_code, species.bto_5letter_code].filter(Boolean).join(' / ')}
						</dd>
					</div>
				{/if}
			</dl>
		</div>
	</a>
</article>

<style>
	.card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		overflow: hidden;
		display: flex;
		flex-direction: column;
		transition: border-color 0.15s;
	}
	.card:hover {
		border-color: var(--color-border-strong);
	}

	.card-link {
		display: flex;
		flex-direction: column;
		flex: 1;
		text-decoration: none;
		color: inherit;
	}
	.card-link:focus {
		outline: none;
	}

	.img-wrap {
		aspect-ratio: 16 / 9;
		background: var(--color-skeleton);
		position: relative;
		overflow: hidden;
	}
	.species-img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.img-fallback {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-ghost);
	}
	.fallback-icon {
		width: 3.5rem;
		height: 3.5rem;
		fill: currentColor;
	}
	.bocc-badge {
		position: absolute;
		top: 0.5rem;
		left: 0.5rem;
		height: 1.25rem;
		padding: 0 0.375rem;
		border-radius: 0.25rem;
		font-size: 0.625rem;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
		line-height: 1;
		box-shadow: 0 1px 3px rgba(0,0,0,0.4);
	}

	.stats {
		padding: 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		flex: 1;
	}

	.name-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.375rem;
		min-width: 0;
	}
	.name-col {
		min-width: 0;
	}
	.common-name {
		margin: 0;
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text);
		line-height: 1.25;
	}
	.sci-name {
		margin: 0.125rem 0 0;
		font-size: 0.6875rem;
		color: var(--color-text-muted);
		font-style: italic;
		line-height: 1.25;
	}

	.badges {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		flex-wrap: wrap;
	}
	.status-badge {
		font-size: 0.625rem;
		font-weight: 600;
		padding: 0.125rem 0.375rem;
		border-radius: 0.25rem;
	}

	.det-count {
		font-size: 1.25rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--color-accent-text);
	}
	.det-label {
		font-size: 0.75rem;
		font-weight: 400;
		color: var(--color-text-muted);
		margin-left: 0.25rem;
	}

	.detail-list {
		margin: auto 0 0;
		font-size: 0.75rem;
		color: var(--color-text-muted);
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}
	.detail-row {
		display: flex;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.detail-row dd {
		margin: 0;
		color: var(--color-text-3);
	}
	.detail-row dt {
		margin: 0;
	}
</style>
