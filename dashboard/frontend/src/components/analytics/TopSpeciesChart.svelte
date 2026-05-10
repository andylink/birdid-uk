<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getTopSpecies, type Period, type TopSpeciesEntry } from '$lib/api';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	// Truncate long species names for the y-axis labels.
	function truncate(s: string, max = 28): string {
		return s.length > max ? s.slice(0, max - 1) + '…' : s;
	}

	async function fetchAndRender(p: Period) {
		loading = true;
		empty = false;
		error = null;
		try {
			const data: TopSpeciesEntry[] = await getTopSpecies(p);

			if (!data.length) {
				empty = true;
				if (chart) { chart.data.labels = []; chart.data.datasets[0].data = []; chart.update('none'); }
				return;
			}

			const labels = data.map(d => truncate(d.species));
			const counts = data.map(d => d.count);

			if (chart) {
				chart.data.labels = labels;
				chart.data.datasets[0].data = counts;
				chart.update();
				return;
			}

			if (!canvas) return;

			const { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip } =
				await import('chart.js');
			Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

			chart = new Chart(canvas, {
				type: 'bar',
				data: {
					labels,
					datasets: [{
						label: 'Detections',
						data: counts,
						backgroundColor: 'rgba(52,211,153,0.75)',
						borderColor: '#34d399',
						borderWidth: 1,
						borderRadius: 3,
					}]
				},
				options: {
					indexAxis: 'y',
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { display: false },
						tooltip: {
							callbacks: { label: (ctx) => ` ${ctx.raw} detections` }
						}
					},
					scales: {
						x: {
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: { color: '#94a3b8' },
							beginAtZero: true,
						},
						y: {
							grid: { display: false },
							ticks: { color: '#94a3b8', font: { size: 11 } },
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

	$effect(() => { fetchAndRender(period); });

	onDestroy(() => chart?.destroy());
</script>

<div class="bg-slate-900 border border-slate-800 rounded-lg flex flex-col h-80">
	<h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest px-4 pt-3 pb-2 shrink-0">
		Top 10 Species
	</h3>
	<div class="flex-1 relative px-3 pb-3 min-h-0">
		<canvas bind:this={canvas} class="w-full h-full" class:invisible={loading || empty || !!error}></canvas>
		{#if loading}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">Loading…</div>
		{:else if empty}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">No detections in this period.</div>
		{:else if error}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">{error}</div>
		{/if}
	</div>
</div>
