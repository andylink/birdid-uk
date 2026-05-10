<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { createSSE } from '$lib/sse';
	import type { Detection } from '$lib/api';
	import DetectionCard from './DetectionCard.svelte';

	let { maxItems = 100 }: { maxItems?: number } = $props();

	let detections = $state<Detection[]>([]);
	let sse: ReturnType<typeof createSSE> | null = null;
	let connected = $state(false);

	onMount(() => {
		sse = createSSE('/stream/detections');
		sse.on('detection', (raw) => {
			const d = raw as Detection;
			detections = [d, ...detections].slice(0, maxItems);
			connected = true;
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
