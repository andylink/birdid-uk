<script lang="ts">
	import type { Detection } from '$lib/api';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatTime, formatDate } from '$lib/time';
	import { BOCC_COLOR } from '$lib/bto';
	import Spectrogram from './Spectrogram.svelte';

	let { detection }: { detection: Detection } = $props();

	const time      = $derived(formatTime(detection.timestamp));
	const date      = $derived(formatDate(detection.timestamp));
	const badgeClass = $derived(confidenceBadgeClass(detection.confidence));

	// Notable = UK Red List, Rare, or Very rare
	const isNotable = $derived(
		detection.uk_bocc === 'Red' ||
		detection.species_status === 'Rare' ||
		detection.species_status === 'Very rare'
	);

	const notableLabel = $derived(
		detection.uk_bocc === 'Red'                      ? 'Red List'
		: detection.species_status === 'Very rare'       ? 'Very rare'
		: 'Rare'
	);

	const isFlagged   = $derived(detection.flagged        === 1);
	const cvRan       = $derived(detection.cross_validated === 1);
	const cvAgreed    = $derived(cvRan && detection.cv_agree === 1);
	const cvDisagreed = $derived(cvRan && detection.cv_agree === 0);
</script>

<article
	class="detection-card"
	class:notable={isNotable}
	class:flagged={isFlagged && !isNotable}
>
	<!-- Vertical confidence bar on the left edge -->
	<div class="conf-bar-wrap" aria-label="Confidence {formatConfidence(detection.confidence)}">
		<div class="conf-bar-track">
			<div
				class="conf-bar-fill"
				class:fill-notable={isNotable}
				class:fill-flagged={isFlagged && !isNotable}
				style:height="{detection.confidence * 100}%"
			></div>
		</div>
	</div>

	<div class="detection-body">
		<div class="detection-top">
			<div class="detection-name-row">
				<span class="species-name" class:species-notable={isNotable}>
					{detection.species}
				</span>
				<span class={badgeClass}>{formatConfidence(detection.confidence)}</span>
				{#if isNotable}
					<span
						class="micro-badge"
						style="background-color: {BOCC_COLOR.Red}22; color: {BOCC_COLOR.Red}"
					>
						{notableLabel}
					</span>
				{/if}
				{#if isFlagged}
					<span class="micro-badge flagged-badge">Flagged</span>
				{:else if cvAgreed}
					<span class="micro-badge cv-agree-badge">CV ✓</span>
				{/if}
			</div>
			<time class="detection-time tabular" datetime={detection.timestamp}>{time}</time>
		</div>

		<div class="detection-date">{date}</div>

		<Spectrogram filename={detection.filename} species={detection.species} />

		<!-- Cross-validation detail: shown when a second model also ran -->
		{#if cvRan}
			<div class="cv-detail">
				<span>primary: <span class="tabular">{detection.model ?? '—'}</span>
					{detection.primary_confidence != null ? formatConfidence(detection.primary_confidence) : ''}</span>
				{#if cvAgreed}
					<span class="cv-agree">
						{detection.cv_secondary_model} agrees
						{detection.cv_confidence != null ? formatConfidence(detection.cv_confidence) : ''}
					</span>
				{:else if cvDisagreed}
					<span class="cv-disagree">
						{detection.cv_secondary_model} → {detection.cv_species ?? 'no match'}
						{detection.cv_confidence != null ? formatConfidence(detection.cv_confidence) : ''}
					</span>
				{/if}
			</div>
		{/if}
	</div>
</article>

<style>
	.detection-card {
		display: flex;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--color-border);
		transition: background-color 0.15s;
	}
	.detection-card:hover {
		background: var(--color-surface-2);
	}
	/* Red left border for conservation-notable species */
	.detection-card.notable {
		border-left: 2px solid #ef4444;
		background: rgba(239, 68, 68, 0.03);
	}
	/* Amber left border for manually flagged detections */
	.detection-card.flagged {
		border-left: 2px solid #f59e0b;
		background: rgba(245, 158, 11, 0.03);
	}

	/* Vertical confidence bar */
	.conf-bar-wrap {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.25rem;
		padding-top: 0.125rem;
	}
	.conf-bar-track {
		width: 0.25rem;
		height: 3rem;
		border-radius: 9999px;
		background: var(--color-skeleton-2);
		position: relative;
		overflow: hidden;
	}
	/* Fill grows from the bottom; height is set by confidence (0–100%) */
	.conf-bar-fill {
		position: absolute;
		bottom: 0;
		left: 0;
		right: 0;
		border-radius: 9999px;
		background: #10b981;
		transition: height 0.3s;
	}
	.conf-bar-fill.fill-notable { background: #ef4444; }
	.conf-bar-fill.fill-flagged { background: #f59e0b; }

	.detection-body {
		flex: 1;
		min-width: 0;
	}
	.detection-top {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.detection-name-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
		min-width: 0;
	}
	.species-name {
		font-weight: 600;
		color: var(--color-text);
	}
	.species-name.species-notable {
		color: #ef4444;
	}
	.detection-time {
		font-size: 0.75rem;
		color: var(--color-text-muted);
		flex-shrink: 0;
	}
	.detection-date {
		font-size: 0.75rem;
		color: var(--color-text-muted);
		margin-top: 0.125rem;
	}

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

	/* Cross-validation result row below the spectrogram */
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
</style>
