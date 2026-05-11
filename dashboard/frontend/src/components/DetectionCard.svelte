<script lang="ts">
	import type { Detection } from '$lib/api';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatTime, formatDate } from '$lib/time';
	import { BOCC_COLOR } from '$lib/bto';
	import Spectrogram from './Spectrogram.svelte';

	let { detection }: { detection: Detection } = $props();

	const time = $derived(formatTime(detection.timestamp));
	const date = $derived(formatDate(detection.timestamp));
	const badgeClass = $derived(confidenceBadgeClass(detection.confidence));

	// A detection is "notable" if the species is on the Red BoCC list or is Rare/Very rare
	const isNotable = $derived(
		detection.uk_bocc === 'Red' ||
		detection.species_status === 'Rare' ||
		detection.species_status === 'Very rare'
	);

	// Label shown in the notable badge
	const notableLabel = $derived(
		detection.uk_bocc === 'Red' ? 'Red List'
		: detection.species_status === 'Very rare' ? 'Very rare'
		: 'Rare'
	);

	// Cross-validation state
	const isFlagged   = $derived(detection.flagged === 1);
	const cvRan       = $derived(detection.cross_validated === 1);
	const cvAgreed    = $derived(cvRan && detection.cv_agree === 1);
	const cvDisagreed = $derived(cvRan && detection.cv_agree === 0);
</script>

<article
	class="flex gap-3 px-4 py-3 border-b border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-900/50 transition-colors
	       {isNotable ? 'border-l-2 border-l-red-500 bg-red-50/50 dark:bg-red-950/10' : ''}
	       {isFlagged && !isNotable ? 'border-l-2 border-l-amber-400 bg-amber-50/40 dark:bg-amber-950/10' : ''}"
>
	<!-- Confidence bar -->
	<div class="flex flex-col items-center gap-1 pt-0.5">
		<div
			class="w-1 rounded-full bg-slate-300 dark:bg-slate-700 relative overflow-hidden"
			style="height: 48px"
			aria-label="Confidence {formatConfidence(detection.confidence)}"
		>
			<div
				class="absolute bottom-0 left-0 right-0 rounded-full transition-all
				       {isNotable ? 'bg-red-500' : isFlagged ? 'bg-amber-400' : 'bg-emerald-500'}"
				style="height: {detection.confidence * 100}%"
			></div>
		</div>
	</div>

	<div class="flex-1 min-w-0">
		<div class="flex items-start justify-between gap-2">
			<div class="flex items-center gap-2 flex-wrap min-w-0">
				<span class="font-semibold {isNotable ? 'text-red-600 dark:text-red-200' : 'text-slate-900 dark:text-slate-100'}">{detection.species}</span>
				<span class="text-xs px-1.5 py-0.5 rounded-full font-mono {badgeClass}">
					{formatConfidence(detection.confidence)}
				</span>
				{#if isNotable}
					<span
						class="text-[9px] font-bold px-1.5 py-px rounded"
						style="background-color: {BOCC_COLOR.Red}22; color: {BOCC_COLOR.Red}"
					>
						{notableLabel}
					</span>
				{/if}
				{#if isFlagged}
					<span class="text-[9px] font-bold px-1.5 py-px rounded bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
						Flagged
					</span>
				{:else if cvAgreed}
					<span class="text-[9px] font-medium px-1.5 py-px rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
						CV ✓
					</span>
				{/if}
			</div>
			<time class="text-xs text-slate-500 tabular-nums shrink-0" datetime={detection.timestamp}>
				{time}
			</time>
		</div>

		<div class="text-xs text-slate-500 mt-0.5">
			{date}
		</div>

		<!-- Audio player + spectrogram -->
		<Spectrogram filename={detection.filename} species={detection.species} />

		<!-- Cross-validation detail (only when CV ran) -->
		{#if cvRan}
			<div class="mt-1.5 text-[10px] text-slate-400 dark:text-slate-500 flex flex-wrap gap-x-3 gap-y-0.5">
				<span>primary: <span class="font-mono">{detection.model ?? '—'}</span> {detection.primary_confidence != null ? formatConfidence(detection.primary_confidence) : ''}</span>
				{#if cvAgreed}
					<span class="text-emerald-600 dark:text-emerald-400">
						{detection.cv_secondary_model} agrees {detection.cv_confidence != null ? formatConfidence(detection.cv_confidence) : ''}
					</span>
				{:else if cvDisagreed}
					<span class="text-amber-600 dark:text-amber-400">
						{detection.cv_secondary_model} → {detection.cv_species ?? 'no match'} {detection.cv_confidence != null ? formatConfidence(detection.cv_confidence) : ''}
					</span>
				{/if}
			</div>
		{/if}
	</div>
</article>

