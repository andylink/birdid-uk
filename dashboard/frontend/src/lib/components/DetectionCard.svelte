<script lang="ts">
	import type { Detection } from '$lib/api';
	import { adminDeleteDetection, adminSetVerification } from '$lib/api';
	import { auth } from '$lib/auth';
	import { untrack } from 'svelte';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatTime, formatDate } from '$lib/time';
	import { BOCC_COLOR } from '$lib/bto';
	import Spectrogram from './Spectrogram.svelte';

	let {
		detection,
		ondelete,
	}: {
		detection:  Detection;
		ondelete?:  (id: number) => void;
	} = $props();

	// Local copy of verification_status so admin toggling is instant.
	let verificationStatus = $state(untrack(() => detection.verification_status ?? 'unverified'));
	let verifying = $state(false);
	let deleting  = $state(false);

	const time       = $derived(formatTime(detection.timestamp));
	const date       = $derived(formatDate(detection.timestamp));
	const badgeClass = $derived(confidenceBadgeClass(detection.confidence));

	// Notable = UK Red List, Rare, or Very rare
	const isNotable = $derived(
		detection.uk_bocc === 'Red' ||
		detection.species_status === 'Rare' ||
		detection.species_status === 'Very rare'
	);

	const notableLabel = $derived(
		detection.uk_bocc === 'Red'                ? 'Red List'
		: detection.species_status === 'Very rare' ? 'Very rare'
		: 'Rare'
	);

	const cvRan       = $derived(detection.cross_validated === 1);
	const cvAgreed    = $derived(cvRan && detection.cv_agree === 1);
	const cvDisagreed = $derived(cvRan && detection.cv_agree === 0);

	async function handleDelete() {
		if (deleting) return;
		deleting = true;
		try {
			await adminDeleteDetection(detection.id);
			ondelete?.(detection.id);
		} finally {
			deleting = false;
		}
	}

	// Set verification_status to an explicit target value.
	async function handleSetVerification(target: string) {
		if (verifying) return;
		verifying = true;
		try {
			const result = await adminSetVerification(detection.id, target);
			verificationStatus = result.verification_status;
		} finally {
			verifying = false;
		}
	}
</script>

<article
	class="detection-card"
	class:notable={isNotable}
	class:manually-human={verificationStatus === 'human' && !isNotable}
>
	<!-- Vertical confidence bar on the left edge -->
	<div class="conf-bar-wrap" aria-label="Confidence {formatConfidence(detection.confidence)}">
		<div class="conf-bar-track">
			<div
				class="conf-bar-fill"
				class:fill-notable={isNotable}
				class:fill-human={verificationStatus === 'human' && !isNotable}
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
				<!-- Verification status badge — shows how the detection was approved -->
			{#if verificationStatus === 'human'}
				<span class="micro-badge badge-human" title="Verified by a human">Human ✓</span>
				{:else if verificationStatus === 'cv'}
					<span class="micro-badge badge-cv" title="Both models agreed on this species">CV ✓</span>
				{:else if verificationStatus === 'auto'}
					<span class="micro-badge badge-auto" title="Auto-approved: confidence above threshold">Auto ✓</span>
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

		<!-- Admin controls: shown when logged in.
		     Verify   → mark as human-verified.
		     Unverify → reset to unverified (shown when status is auto, cv, or human). -->
		{#if $auth.authenticated}
			<div class="admin-row">
				{#if verificationStatus !== 'human'}
					<button
						class="admin-btn verify-btn"
						onclick={() => handleSetVerification('human')}
						disabled={verifying}
						title="Mark as human-verified"
					>Verify</button>
				{/if}
				{#if verificationStatus !== 'unverified'}
					<button
						class="admin-btn unverify-btn"
						onclick={() => handleSetVerification('unverified')}
						disabled={verifying}
						title="Reset to unverified"
					>Unverify</button>
				{/if}
				<button
					class="admin-btn delete-btn"
					onclick={handleDelete}
					disabled={deleting}
					title="Delete this detection and its audio clip"
				>
					{deleting ? '…' : 'Delete'}
				</button>
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
	/* Blue left border for human-verified detections */
	.detection-card.manually-human {
		border-left: 2px solid #3b82f6;
		background: rgba(59, 130, 246, 0.03);
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
	.conf-bar-fill.fill-human   { background: #3b82f6; }

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

	/* Admin controls: verify and delete buttons shown when logged in */
	.admin-row {
		display: flex;
		gap: 0.375rem;
		margin-top: 0.375rem;
	}
	.admin-btn {
		padding: 0.1875rem 0.5rem;
		border-radius: 0.25rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		font-size: 0.625rem;
		font-weight: 600;
		cursor: pointer;
		color: var(--color-text-muted);
		transition: opacity 0.15s, background-color 0.15s, color 0.15s, border-color 0.15s;
	}
	.admin-btn:disabled { opacity: 0.4; cursor: not-allowed; }

	.verify-btn:hover:not(:disabled) {
		background: rgba(59, 130, 246, 0.12);
		color: #3b82f6;
		border-color: #3b82f6;
	}
	.unverify-btn:hover:not(:disabled) {
		background: rgba(245, 158, 11, 0.12);
		color: #f59e0b;
		border-color: #f59e0b;
	}
	.delete-btn:hover:not(:disabled) {
		background: rgba(239, 68, 68, 0.12);
		color: #ef4444;
		border-color: #ef4444;
	}
</style>
