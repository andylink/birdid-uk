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

	// One entry per notable species seen since the page loaded (deduplicated by name)
	let notableMap = $state<Map<string, Detection>>(new Map());

	const notableList = $derived([...notableMap.values()]);

	function isNotable(d: Detection): boolean {
		return d.uk_bocc === 'Red' || d.species_status === 'Rare' || d.species_status === 'Very rare';
	}

	onMount(() => {
		sse = createSSE('/stream/detections');
		sse.on('detection', (raw) => {
			const d = raw as Detection;
			// Prepend new detection; trim list to maxItems
			detections = [d, ...detections].slice(0, maxItems);
			connected = true;
			// Add to notable strip if not already shown
			if (isNotable(d) && !notableMap.has(d.species)) {
				const next = new Map(notableMap);
				next.set(d.species, d);
				notableMap = next;
			}
		});
	});

	onDestroy(() => sse?.close());
</script>

<section class="feed" aria-label="Live detection feed">
	<header class="feed-header">
		<span class="feed-title">Live Feed</span>
		<!-- Dot pulses green when the SSE stream is connected -->
		<span
			class="feed-dot"
			class:connected
			aria-label={connected ? 'Connected' : 'Connecting…'}
		></span>
		{#if detections.length}
			<span class="feed-count">
				{detections.length} detection{detections.length !== 1 ? 's' : ''}
			</span>
		{/if}
	</header>

	<!-- Notable species seen this session (Red List, Rare, Very rare) -->
	{#if notableList.length > 0}
		<div class="notable-strip">
			<p class="notable-heading">Notable this session</p>
			<div class="notable-pills">
				{#each notableList as d (d.species)}
					{@const label = d.uk_bocc === 'Red' ? 'Red List'
						: d.species_status === 'Very rare' ? 'Very rare' : 'Rare'}
					{@const color = BOCC_COLOR[d.uk_bocc ?? ''] ?? BOCC_COLOR.Red}
					<span
						class="notable-pill"
						style="border-color: {color}44; color: {color}; background-color: {color}11"
						title="{d.species} — {label}"
					>
						<span class="notable-dot" style="background-color: {color}"></span>
						{d.species}
					</span>
				{/each}
			</div>
		</div>
	{/if}

	<div class="feed-list" role="feed" aria-live="polite" aria-label="Bird detections">
		{#if detections.length === 0}
			<div class="feed-empty">
				<svg viewBox="0 0 24 24" class="empty-icon" aria-hidden="true">
					<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
				</svg>
				<p>Waiting for detections…</p>
			</div>
		{:else}
			{#each detections as detection (detection.id)}
				<DetectionCard {detection} />
			{/each}
		{/if}
	</div>
</section>

<style>
	.feed {
		display: flex;
		flex-direction: column;
		height: 100%;
	}

	.feed-header {
		padding: 0.5rem 1rem;
		border-bottom: 1px solid var(--color-border);
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.875rem;
		flex-shrink: 0;
	}
	.feed-title {
		font-weight: 500;
		color: var(--color-text-2);
	}
	.feed-dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 9999px;
		background: var(--color-skeleton-2);
	}
	.feed-dot.connected {
		background: #34d399;
		animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}
	.feed-count {
		margin-left: auto;
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}

	/* Red-tinted strip listing notable species seen this session */
	.notable-strip {
		border-bottom: 1px solid rgba(239, 68, 68, 0.3);
		background: rgba(239, 68, 68, 0.04);
		padding: 0.5rem 0.75rem;
		flex-shrink: 0;
	}
	.notable-heading {
		margin: 0 0 0.375rem;
		font-size: 0.5625rem;
		font-weight: 700;
		color: #ef4444;
		text-transform: uppercase;
		letter-spacing: 0.12em;
	}
	.notable-pills {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem;
	}
	.notable-pill {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		font-size: 0.625rem;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		border: 1px solid;
		font-weight: 500;
	}
	.notable-dot {
		width: 0.375rem;
		height: 0.375rem;
		border-radius: 9999px;
		flex-shrink: 0;
	}

	.feed-list {
		flex: 1;
		overflow-y: auto;
	}
	.feed-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 0.5rem;
		color: var(--color-text-dim);
		padding: 4rem 0;
	}
	.empty-icon {
		width: 2rem;
		height: 2rem;
		fill: currentColor;
		opacity: 0.5;
	}
	.feed-empty p {
		margin: 0;
		font-size: 0.875rem;
	}
</style>
