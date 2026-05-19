<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getByHour } from '$lib/api';
	import { localToday } from '$lib/time';

	type Mode = 'today' | 'alltime';

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let error   = $state<string | null>(null);
	let mode    = $state<Mode>('today');
	let timer: ReturnType<typeof setInterval> | null = null;

	// Read CSS custom properties so the chart respects light/dark theme
	function chartColors() {
		const s = getComputedStyle(document.documentElement);
		return {
			grid: s.getPropertyValue('--chart-grid').trim() || 'rgba(255,255,255,0.05)',
			tick: s.getPropertyValue('--chart-tick').trim() || '#94a3b8',
		};
	}

	// Called when the theme changes; updates axis colours without rebuilding the chart
	function applyColorsToChart() {
		if (!chart) return;
		const { grid, tick } = chartColors();
		const scales = chart.options.scales as any;
		if (scales?.x?.grid)  scales.x.grid.color  = grid;
		if (scales?.x?.ticks) scales.x.ticks.color = tick;
		if (scales?.y?.grid)  scales.y.grid.color  = grid;
		if (scales?.y?.ticks) scales.y.ticks.color = tick;
		chart.update('none');
	}

	async function loadData(m: Mode) {
		return await getByHour(m === 'today' ? localToday() : undefined);
	}

	async function switchMode(next: Mode) {
		if (next === mode) return;
		mode = next;
		try {
			const hourly = await loadData(next);
			if (chart) { chart.data.datasets[0].data = hourly.data; chart.update(); }
		} catch (e) {
			console.error('ActivityChart switch error:', e);
		}
		resetTimer();
	}

	// Silently refresh data; no loading spinner needed for periodic updates
	async function refresh() {
		try {
			const hourly = await loadData(mode);
			if (chart) { chart.data.datasets[0].data = hourly.data; chart.update('none'); }
		} catch (e) {
			console.error('ActivityChart refresh error:', e);
		}
	}

	// Refresh every 60s for today, every 5min for all-time
	function resetTimer() {
		if (timer !== null) clearInterval(timer);
		timer = setInterval(refresh, mode === 'today' ? 60_000 : 300_000);
	}

	onMount(async () => {
		try {
			const hourly = await loadData(mode);

			// Dynamic import keeps Chart.js out of the initial bundle
			const { Chart, LineController, LineElement, LinearScale, CategoryScale,
				PointElement, Tooltip, Filler } = await import('chart.js');
			Chart.register(LineController, LineElement, LinearScale, CategoryScale,
				PointElement, Tooltip, Filler);

			if (!canvas) return;

			const { grid, tick } = chartColors();

			chart = new Chart(canvas, {
				type: 'line',
				data: {
					labels: hourly.labels,
					datasets: [{
						label: 'Detections by hour',
						data: hourly.data,
						borderColor: '#34d399',
						backgroundColor: 'rgba(52,211,153,0.15)',
						fill: true,
						tension: 0.4,
						pointRadius: 3,
						pointHoverRadius: 5,
					}]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { display: false },
						tooltip: {
							callbacks: {
								title: (ctx) => `${ctx[0].label}`,
								label: (ctx) => ` ${ctx.raw} detections`,
							}
						}
					},
					scales: {
						x: {
							grid: { color: grid },
							ticks: {
								color: tick,
								maxTicksLimit: 8,
								// Show only every third label to avoid crowding
								callback: (_val, idx) => idx % 3 === 0 ? hourly.labels[idx] : ''
							}
						},
						y: {
							grid: { color: grid },
							ticks: { color: tick },
							beginAtZero: true,
						}
					}
				}
			});

			resetTimer();
		} catch (e) {
			console.error('ActivityChart error:', e);
			error = e instanceof Error ? e.message : 'Could not load activity data.';
		} finally {
			loading = false;
		}
	});

	onMount(() => {
		document.addEventListener('themechange', applyColorsToChart);
		return () => document.removeEventListener('themechange', applyColorsToChart);
	});

	onDestroy(() => {
		chart?.destroy();
		if (timer !== null) clearInterval(timer);
	});
</script>

<div class="activity-chart">
	<div class="activity-header">
		<h2 class="activity-title">Activity by Hour</h2>
		<div class="mode-toggle" role="group" aria-label="Time range">
			<button
				class="mode-btn"
				class:active={mode === 'today'}
				onclick={() => switchMode('today')}
			>Today</button>
			<button
				class="mode-btn"
				class:active={mode === 'alltime'}
				onclick={() => switchMode('alltime')}
			>All time</button>
		</div>
	</div>

	<div class="activity-body">
		<!-- Canvas is hidden while loading or on error to avoid a blank flash -->
		<canvas
			bind:this={canvas}
			class="activity-canvas"
			style:visibility={loading || !!error ? 'hidden' : 'visible'}
		></canvas>

		{#if loading}
			<div class="activity-overlay">Loading…</div>
		{:else if error}
			<div class="activity-overlay">{error}</div>
		{/if}
	</div>
</div>

<style>
	.activity-chart {
		display: flex;
		flex-direction: column;
		height: 100%;
	}

	.activity-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem 1rem 0.5rem;
		flex-shrink: 0;
	}

	.activity-title {
		margin: 0;
		font-size: 0.625rem;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	.mode-toggle {
		display: flex;
		font-size: 0.75rem;
		border-radius: 0.25rem;
		overflow: hidden;
		border: 1px solid var(--color-border-strong);
	}
	.mode-btn {
		padding: 0.125rem 0.5rem;
		border: none;
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
		transition: background-color 0.15s, color 0.15s;
	}
	.mode-btn:hover { color: var(--color-text); }
	.mode-btn.active {
		background: #059669;
		color: #fff;
	}

	.activity-body {
		flex: 1;
		position: relative;
		padding: 0 0.75rem 0.75rem;
		min-height: 0;
	}
	.activity-canvas {
		width: 100%;
		height: 100%;
	}
	.activity-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-muted);
		font-size: 0.875rem;
	}
</style>
