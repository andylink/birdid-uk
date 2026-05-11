<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getByHour } from '$lib/api';
	import { localToday } from '$lib/time';

	type Mode = 'today' | 'alltime';

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let error = $state<string | null>(null);
	let mode = $state<Mode>('today');
	let timer: ReturnType<typeof setInterval> | null = null;

	function chartColors() {
		const s = getComputedStyle(document.documentElement);
		return {
			grid: s.getPropertyValue('--chart-grid').trim() || 'rgba(255,255,255,0.05)',
			tick: s.getPropertyValue('--chart-tick').trim() || '#94a3b8',
		};
	}

	function applyColorsToChart() {
		if (!chart) return;
		const { grid, tick } = chartColors();
		const scales = chart.options.scales as any;
		if (scales?.x?.grid) scales.x.grid.color = grid;
		if (scales?.x?.ticks) scales.x.ticks.color = tick;
		if (scales?.y?.grid) scales.y.grid.color = grid;
		if (scales?.y?.ticks) scales.y.ticks.color = tick;
		chart.update('none');
	}

	async function loadData(m: Mode) {
		const hourly = await getByHour(m === 'today' ? localToday() : undefined);
		return hourly;
	}

	async function switchMode(next: Mode) {
		if (next === mode) return;
		mode = next;
		try {
			const hourly = await loadData(next);
			if (chart) {
				chart.data.datasets[0].data = hourly.data;
				chart.update();
			}
		} catch (e) {
			console.error('ActivityChart switch error:', e);
		}
		resetTimer();
	}

	async function refresh() {
		try {
			const hourly = await loadData(mode);
			if (chart) {
				chart.data.datasets[0].data = hourly.data;
				chart.update('none');
			}
		} catch (e) {
			console.error('ActivityChart refresh error:', e);
		}
	}

	function resetTimer() {
		if (timer !== null) clearInterval(timer);
		// Today refreshes every 60 s; all-time changes slowly so every 5 min is fine.
		timer = setInterval(refresh, mode === 'today' ? 60_000 : 300_000);
	}

	onMount(async () => {
		try {
			const hourly = await loadData(mode);

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
	return () => {
		document.removeEventListener('themechange', applyColorsToChart);
	};
});

onDestroy(() => {
	chart?.destroy();
	if (timer !== null) clearInterval(timer);
});
</script>

<div class="flex flex-col h-full">
	<div class="flex items-center justify-between px-4 pt-3 pb-2 shrink-0">
		<h2 class="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-widest">
			Activity by Hour
		</h2>
		<div class="flex text-xs rounded overflow-hidden border border-slate-300 dark:border-slate-700">
			<button
				class="px-2 py-0.5 transition-colors {mode === 'today'
					? 'bg-emerald-600 text-white'
					: 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'}"
				onclick={() => switchMode('today')}
			>
				Today
			</button>
			<button
				class="px-2 py-0.5 transition-colors {mode === 'alltime'
					? 'bg-emerald-600 text-white'
					: 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'}"
				onclick={() => switchMode('alltime')}
			>
				All time
			</button>
		</div>
	</div>

	<div class="flex-1 relative px-3 pb-3 min-h-0">
		<canvas bind:this={canvas} class="w-full h-full" class:invisible={loading || !!error}></canvas>

		{#if loading}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">
				Loading…
			</div>
		{:else if error}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">
				{error}
			</div>
		{/if}
	</div>
</div>
