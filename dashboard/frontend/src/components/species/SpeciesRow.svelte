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
	class="flex items-center gap-3 px-3 py-2.5 border-b border-slate-200 dark:border-slate-800
	       hover:bg-slate-100 dark:hover:bg-slate-900/60 transition-colors focus:outline-none
	       focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-500"
	aria-label="View recordings for {species.species}"
>
	<!-- Thumbnail with group badge overlay -->
	<div class="w-11 h-11 rounded bg-slate-200 dark:bg-slate-800 overflow-hidden shrink-0 relative">
		{#if imgError}
			<div class="w-full h-full flex items-center justify-center text-slate-300 dark:text-slate-700">
				<svg viewBox="0 0 24 24" class="w-6 h-6 fill-current" aria-hidden="true">
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
		<!-- Group badge: bottom-right corner of thumbnail -->
		<span
			class="absolute bottom-0 right-0 h-4 px-1 rounded-tl text-[9px] font-bold
			       flex items-center text-white leading-none"
			style="background-color: {groupBadgeColor(species.group_name)}"
			title={species.group_name ?? undefined}
		>
			{speciesInitials(species.species, species.bto_5letter_code, species.bto_2letter_code)}
		</span>
	</div>

	<!-- Name column: common name + confidence badge, scientific name, conservation pills -->
	<div class="flex flex-col gap-0.5 flex-1 min-w-0">
		<div class="flex items-center gap-2">
			<span class="font-semibold text-slate-900 dark:text-slate-100 text-sm truncate">{species.species}</span>
			<span class="text-xs px-1.5 py-0.5 rounded-full font-mono shrink-0 {avgBadge}">
				{formatConfidence(species.avg_confidence)}
			</span>
		</div>
		{#if species.scientific_name}
			<span class="text-[11px] text-slate-500 italic truncate">{species.scientific_name}</span>
		{/if}
		{#if species.uk_bocc || statusStyle}
			<div class="flex items-center gap-1 mt-0.5">
				{#if species.uk_bocc}
					<span
						class="text-[9px] font-semibold px-1 py-px rounded"
						style="background-color: {BOCC_COLOR[species.uk_bocc]}22; color: {BOCC_COLOR[species.uk_bocc]}"
					>
						BoCC {species.uk_bocc}
					</span>
				{/if}
				{#if statusStyle}
					<span
						class="text-[9px] font-semibold px-1 py-px rounded"
						style="background-color: {statusStyle.bg}; color: {statusStyle.text}"
					>
						{species.species_status}
					</span>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Detections -->
	<div class="w-24 text-right tabular-nums text-sm font-bold text-emerald-500 dark:text-emerald-400">
		{species.detections.toLocaleString()}
	</div>

	<!-- Peak confidence -->
	<div class="w-16 text-right tabular-nums text-xs text-slate-500 dark:text-slate-400 hidden sm:block">
		{formatConfidence(species.peak_confidence)}
	</div>

	<!-- First seen -->
	<div class="w-28 text-right text-xs text-slate-500 hidden md:block">
		{formatFullDate(species.first_detected)}
	</div>

	<!-- Last seen -->
	<div class="w-28 text-right text-xs text-slate-500 hidden md:block">
		{formatFullDate(species.last_detected)}
	</div>
</a>
