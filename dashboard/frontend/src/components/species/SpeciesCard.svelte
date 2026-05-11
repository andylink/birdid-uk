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

<article
	class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden flex flex-col
	       hover:border-slate-300 dark:hover:border-slate-700 transition-colors"
>
	<a
		href="/species/{encodeURIComponent(species.species)}?from=species"
		class="flex flex-col flex-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
		aria-label="View recordings for {species.species}"
	>
	<!-- Species image -->
	<div class="aspect-video bg-slate-200 dark:bg-slate-800 relative overflow-hidden">
		{#if imgError}
			<div class="absolute inset-0 flex items-center justify-center text-slate-300 dark:text-slate-700">
				<svg viewBox="0 0 24 24" class="w-14 h-14 fill-current" aria-hidden="true">
					<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
				</svg>
			</div>
		{:else}
			<img
				src={speciesImageUrl(species.species)}
				alt={species.species}
				class="w-full h-full object-cover"
				onerror={() => (imgError = true)}
				loading="lazy"
			/>
		{/if}

		<!-- BoCC overlay -->
		{#if species.uk_bocc}
			<span
				class="absolute top-2 left-2 h-5 px-1.5 rounded text-[10px] font-bold
				       flex items-center leading-none shadow"
				style="background-color: {BOCC_COLOR[species.uk_bocc]}; color: #0f172a"
			>
				{species.uk_bocc}
			</span>
		{/if}
	</div>

	<!-- Stats -->
	<div class="p-3 flex flex-col gap-2 flex-1">
		<!-- Name + avg confidence badge -->
		<div class="flex items-start justify-between gap-1.5 min-w-0">
			<div class="min-w-0">
				<h3 class="font-semibold text-slate-900 dark:text-slate-100 text-sm leading-tight">{species.species}</h3>
				{#if species.scientific_name}
					<p class="text-[11px] text-slate-500 italic leading-tight mt-0.5 truncate">
						{species.scientific_name}
					</p>
				{/if}
			</div>
			<span class="text-xs px-1.5 py-0.5 rounded-full font-mono shrink-0 {avgBadge}">
				{formatConfidence(species.avg_confidence)}
			</span>
		</div>

		<!-- Conservation badges -->
		{#if statusStyle}
			<div class="flex items-center gap-1.5 flex-wrap">
				{#if statusStyle}
					<span
						class="text-[10px] font-semibold px-1.5 py-0.5 rounded"
						style="background-color: {statusStyle.bg}; color: {statusStyle.text}"
					>
						{species.species_status}
					</span>
				{/if}
			</div>
		{/if}

		<!-- Detection count -->
		<div class="text-xl font-bold tabular-nums text-emerald-500 dark:text-emerald-400">
			{species.detections.toLocaleString()}<span class="text-xs font-normal text-slate-500 ml-1">detections</span>
		</div>

		<!-- Detail rows -->
		<dl class="text-xs text-slate-500 space-y-0.5 mt-auto">
			<div class="flex justify-between gap-2">
				<dt>Peak</dt>
				<dd class="font-mono text-slate-600 dark:text-slate-300">{formatConfidence(species.peak_confidence)}</dd>
			</div>
			<div class="flex justify-between gap-2">
				<dt>First seen</dt>
				<dd class="text-slate-500 dark:text-slate-400">{formatFullDate(species.first_detected)}</dd>
			</div>
			<div class="flex justify-between gap-2">
				<dt>Last seen</dt>
				<dd class="text-slate-500 dark:text-slate-400">{formatFullDate(species.last_detected)}</dd>
			</div>
			{#if species.bto_5letter_code || species.bto_2letter_code}
				<div class="flex justify-between gap-2">
					<dt>BTO code</dt>
					<dd class="font-mono text-slate-500 dark:text-slate-400">
						{[species.bto_5letter_code, species.bto_2letter_code].filter(Boolean).join(' / ')}
					</dd>
				</div>
			{/if}
		</dl>
	</div>
	</a>
</article>
