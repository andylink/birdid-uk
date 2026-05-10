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
</script>

<article
	class="flex gap-3 px-4 py-3 border-b border-slate-800 hover:bg-slate-900/50 transition-colors
	       {isNotable ? 'border-l-2 border-l-red-500 bg-red-950/10' : ''}"
>
	<!-- Confidence bar -->
	<div class="flex flex-col items-center gap-1 pt-0.5">
		<div
			class="w-1 rounded-full bg-slate-700 relative overflow-hidden"
			style="height: 48px"
			aria-label="Confidence {formatConfidence(detection.confidence)}"
		>
			<div
				class="absolute bottom-0 left-0 right-0 rounded-full transition-all
				       {isNotable ? 'bg-red-500' : 'bg-emerald-500'}"
				style="height: {detection.confidence * 100}%"
			></div>
		</div>
	</div>

	<div class="flex-1 min-w-0">
		<div class="flex items-start justify-between gap-2">
			<div class="flex items-center gap-2 flex-wrap min-w-0">
				<span class="font-semibold {isNotable ? 'text-red-200' : 'text-slate-100'}">{detection.species}</span>
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
	</div>
</article>
