<script lang="ts">
	import type { SpeciesStats } from '$lib/api';
	import { speciesImageUrl } from '$lib/api';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatFullDate } from '$lib/time';
	import { BOCC_COLOR, SPECIES_STATUS_STYLE, groupBadgeColor, speciesInitials } from '$lib/bto';

	let { species }: { species: SpeciesStats } = $props();

	let imgError = $state(false);

	const avgBadge = $derived(confidenceBadgeClass(species.avg_confidence));
	const statusStyle = $derived(
		species.species_status ? SPECIES_STATUS_STYLE[species.species_status] : null
	);
</script>

<a
	href="/species/{encodeURIComponent(species.species)}?from=species"
	class="row"
	aria-label="View recordings for {species.species}"
>
	<!-- Thumbnail; group-badge overlaid at bottom-right shows taxonomic group initials -->
	<div class="thumb">
		{#if imgError}
			<div class="thumb-fallback">
				<svg viewBox="0 0 24 24" class="thumb-icon" aria-hidden="true">
					<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
				</svg>
			</div>
		{:else}
		<img
			src={speciesImageUrl(species.bto_name ?? species.species)}
			alt={species.species}
			class="thumb-img"
				onerror={() => (imgError = true)}
				loading="lazy"
			/>
		{/if}
		<span
			class="group-badge"
			style="background-color: {groupBadgeColor(species.group_name)}"
			title={species.group_name ?? undefined}
		>
			{speciesInitials(species.species, species.bto_5letter_code, species.bto_2letter_code)}
		</span>
	</div>

	<div class="name-col">
		<div class="name-row">
			<span class="common-name truncate">{species.species}</span>
			<span class="{avgBadge}">{formatConfidence(species.avg_confidence)}</span>
		</div>
		{#if species.scientific_name}
			<span class="sci-name truncate">{species.scientific_name}</span>
		{/if}
		{#if species.uk_bocc || statusStyle}
			<div class="pills">
				{#if species.uk_bocc}
					<!-- Semi-transparent tint derived from the BoCC colour -->
					<span
						class="pill"
						style="background-color: {BOCC_COLOR[species.uk_bocc]}22; color: {BOCC_COLOR[species.uk_bocc]}"
					>
						BoCC {species.uk_bocc}
					</span>
				{/if}
				{#if statusStyle}
					<span
						class="pill"
						style="background-color: {statusStyle.bg}; color: {statusStyle.text}"
					>
						{species.species_status}
					</span>
				{/if}
			</div>
		{/if}
	</div>

	<div class="col-det tabular">{species.detections.toLocaleString()}</div>
	<div class="col-peak tabular hide-sm">{formatConfidence(species.peak_confidence)}</div>
	<div class="col-date hide-md">{formatFullDate(species.first_detected)}</div>
	<div class="col-date hide-md">{formatFullDate(species.last_detected)}</div>
</a>

<style>
	.row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.625rem 0.75rem;
		border-bottom: 1px solid var(--color-border);
		text-decoration: none;
		color: inherit;
		transition: background-color 0.1s;
	}
	.row:hover {
		background: var(--color-surface-2);
	}
	.row:focus {
		outline: none;
	}
	.row:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
	}

	.thumb {
		width: 2.75rem;
		height: 2.75rem;
		border-radius: 0.25rem;
		background: var(--color-skeleton);
		overflow: hidden;
		flex-shrink: 0;
		position: relative;
	}
	.thumb-img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.thumb-fallback {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-ghost);
	}
	.thumb-icon {
		width: 1.5rem;
		height: 1.5rem;
		fill: currentColor;
	}
	/* Badge anchored to bottom-right corner of the thumbnail */
	.group-badge {
		position: absolute;
		bottom: 0;
		right: 0;
		height: 1rem;
		padding: 0 0.25rem;
		border-radius: 0.25rem 0 0 0;
		font-size: 0.5625rem;
		font-weight: 700;
		color: #fff;
		display: flex;
		align-items: center;
		line-height: 1;
	}

	.name-col {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
		flex: 1;
		min-width: 0;
	}
	.name-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.common-name {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text);
	}
	.sci-name {
		font-size: 0.6875rem;
		color: var(--color-text-muted);
		font-style: italic;
	}
	.pills {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		margin-top: 0.125rem;
	}
	.pill {
		font-size: 0.5625rem;
		font-weight: 600;
		padding: 0.0625rem 0.25rem;
		border-radius: 0.25rem;
	}

	/* Fixed-width right columns keep the table-like layout stable */
	.col-det {
		width: 6rem;
		text-align: right;
		font-size: 0.875rem;
		font-weight: 700;
		color: var(--color-accent-text);
		flex-shrink: 0;
	}
	.col-peak {
		width: 4rem;
		text-align: right;
		font-size: 0.75rem;
		color: var(--color-text-muted);
		flex-shrink: 0;
	}
	.col-date {
		width: 7rem;
		text-align: right;
		font-size: 0.75rem;
		color: var(--color-text-muted);
		flex-shrink: 0;
	}

	@media (max-width: 639px) {
		.hide-sm { display: none; }
	}
	@media (max-width: 767px) {
		.hide-md { display: none; }
	}
</style>
