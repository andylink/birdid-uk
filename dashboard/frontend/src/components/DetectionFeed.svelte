<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { createSSE } from '$lib/sse';
	import type { Detection } from '$lib/api';
	import { BOCC_COLOR } from '$lib/bto';
	import DetectionCard from './DetectionCard.svelte';

	let { maxItems = 100 }: { maxItems?: number } = $props();

	let detections = $state<Detection[]>([]);
	let sse: ReturnType<typeof createSSE> | null = null;
	let connected = $state(false);

	// Track unique notable species (Red-list / Rare / Very rare) seen this session
	let notableMap = $state<Map<string, Detection>>(new Map());

	const notableList = $derived([...notableMap.values()]);

	function isNotable(d: Detection): boolean {
		return d.uk_bocc === 'Red' || d.species_status === 'Rare' || d.species_status === 'Very rare';
	}

	onMount(() => {
		sse = createSSE('/stream/detections');
		sse.on('detection', (raw) => {
			const d = raw as Detection;
			detections = [d, ...detections].slice(0, maxItems);
			connected = true;
			if (isNotable(d) && !notableMap.has(d.species)) {
				// Svelte 5: reassign the map to trigger reactivity
				const next = new Map(notableMap);
				next.set(d.species, d);
				notableMap = next;
			}
		});
	});

	onDestroy(() => sse?.close());
</script>

<section class="flex flex-col h-full" aria-label="Live detection feed">
	<header class="px-4 py-2 border-b border-slate-800 flex items-center gap-2 text-sm shrink-0">
		<span class="font-medium text-slate-200">Live Feed</span>
		<span
			class="w-2 h-2 rounded-full {connected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}"
			aria-label={connected ? 'Connected' : 'Connecting…'}
		></span>
		{#if detections.length}
			<span class="ml-auto text-slate-500 text-xs">
				{detections.length} detection{detections.length !== 1 ? 's' : ''}
			</span>
		{/if}
	</header>

	<!-- Notable species section (only visible when at least one has been seen) -->
	{#if notableList.length > 0}
		<div class="border-b border-red-900/40 bg-red-950/20 px-3 py-2 shrink-0">
			<p class="text-[9px] font-bold text-red-500 uppercase tracking-widest mb-1.5">
				Notable this session
			</p>
			<div class="flex flex-wrap gap-1.5">
				{#each notableList as d (d.species)}
					{@const label = d.uk_bocc === 'Red' ? 'Red List'
						: d.species_status === 'Very rare' ? 'Very rare' : 'Rare'}
					{@const color = BOCC_COLOR[d.uk_bocc ?? ''] ?? BOCC_COLOR.Red}
					<span
						class="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border font-medium"
						style="border-color: {color}44; color: {color}; background-color: {color}11"
						title="{d.species} — {label}"
					>
						<span class="w-1.5 h-1.5 rounded-full inline-block shrink-0" style="background-color: {color}"></span>
						{d.species}
					</span>
				{/each}
			</div>
		</div>
	{/if}

	<div class="flex-1 overflow-y-auto" role="feed" aria-live="polite" aria-label="Bird detections">
		{#if detections.length === 0}
			<div class="flex flex-col items-center justify-center h-full text-slate-600 gap-2 py-16">
				<svg viewBox="0 0 24 24" class="w-8 h-8 fill-current opacity-50" aria-hidden="true">
					<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
				</svg>
				<p class="text-sm">Waiting for detections…</p>
			</div>
		{:else}
			{#each detections as detection (detection.id)}
				<DetectionCard {detection} />
			{/each}
		{/if}
	</div>
</section>
