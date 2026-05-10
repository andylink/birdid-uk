<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getByHour, type Period } from '$lib/api';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function fetchAndRender(p: Period) {
		loading = true;
		error = null;
		try {
			// "today" maps to ?date=...; others use ?period=...
			const hourly = p === 'today'
				? await getByHour(todayLocal())
				: await getByHour(undefined, p);

			if (chart) {
				chart.data.datasets[0].data = hourly.data;
				chart.update();
				return;
			}

			if (!canvas) return;

			const { Chart, LineController, LineElement, LinearScale, CategoryScale,
				PointElement, Tooltip, Filler } = await import('chart.js');
			Chart.register(LineController, LineElement, LinearScale, CategoryScale,
				PointElement, Tooltip, Filler);

			chart = new Chart(canvas, {
				type: 'line',
				data: {
					labels: hourly.labels,
					datasets: [{
						label: 'Detections by hour',
						data: hourly.data,
						borderColor: '#818cf8',
						backgroundColor: 'rgba(129,140,248,0.15)',
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
								title: (ctx) => ctx[0].label,
								label: (ctx) => ` ${ctx.raw} detections`,
							}
						}
					},
					scales: {
						x: {
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: {
								color: '#94a3b8',
								maxTicksLimit: 8,
								callback: (_val, idx) => idx % 3 === 0 ? hourly.labels[idx] : '',
							}
						},
						y: {
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: { color: '#94a3b8' },
							beginAtZero: true,
						}
					}
				}
			});
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load data.';
		} finally {
			loading = false;
		}
	}

	function todayLocal(): string {
		const d = new Date();
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	}

	$effect(() => { fetchAndRender(period); });

	onDestroy(() => chart?.destroy());
</script>

<div class="bg-slate-900 border border-slate-800 rounded-lg flex flex-col h-80">
	<h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest px-4 pt-3 pb-2 shrink-0">
		Detections by Time of Day
	</h3>
	<div class="flex-1 relative px-3 pb-3 min-h-0">
		<canvas bind:this={canvas} class="w-full h-full" class:invisible={loading || !!error}></canvas>
		{#if loading}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">Loading…</div>
		{:else if error}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">{error}</div>
		{/if}
	</div>
</div>
