<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		subtitle?: string;
		loading?: boolean;
		empty?: boolean;
		error?: string | null;
		emptyMessage?: string;
		/** CSS height for the card, e.g. "20rem". */
		height?: string;
		/** Bind to get a reference to the canvas element. */
		canvasEl?: HTMLCanvasElement;
		/** Optional slot rendered beside the title (e.g. mode-toggle buttons). */
		headerExtra?: Snippet;
	}

	let {
		title,
		subtitle,
		loading = false,
		empty = false,
		error = null,
		emptyMessage = 'No data for this period.',
		height = '20rem',
		canvasEl = $bindable<HTMLCanvasElement | undefined>(undefined),
		headerExtra,
	}: Props = $props();
</script>

<div class="chart-card" style:height>
	<header class="chart-header">
		<div class="chart-header-text">
			<h3 class="chart-title">{title}</h3>
			{#if subtitle}
				<p class="chart-subtitle">{subtitle}</p>
			{/if}
		</div>
		{#if headerExtra}
			{@render headerExtra()}
		{/if}
	</header>

	<div class="chart-body">
		<!-- Canvas is hidden (not removed) while loading to preserve Chart.js layout -->
		<canvas
			bind:this={canvasEl}
			class="chart-canvas"
			style:visibility={loading || empty || !!error ? 'hidden' : 'visible'}
		></canvas>
		{#if loading}
			<div class="chart-overlay">Loading…</div>
		{:else if empty}
			<div class="chart-overlay">{emptyMessage}</div>
		{:else if error}
			<div class="chart-overlay chart-overlay-error">{error}</div>
		{/if}
	</div>
</div>

<style>
	.chart-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.chart-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.5rem;
		padding: 0.75rem 1rem 0.5rem;
		flex-shrink: 0;
	}

	.chart-header-text {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}

	.chart-title {
		margin: 0;
		font-size: 0.625rem;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	.chart-subtitle {
		margin: 0;
		font-size: 0.625rem;
		color: var(--color-text-dim);
	}

	.chart-body {
		flex: 1;
		position: relative;
		padding: 0 0.75rem 0.75rem;
		min-height: 0;
	}

	.chart-canvas {
		width: 100%;
		height: 100%;
	}

	.chart-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-muted);
		font-size: 0.875rem;
	}

	.chart-overlay-error {
		color: #f87171;
	}
</style>
