<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getNewSpeciesTimeline, type Period, type NewSpeciesEntry } from '$lib/api';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	/** Format YYYY-MM-DD → "09 May" */
	function fmtDay(iso: string): string {
		const d = new Date(iso + 'T00:00:00');
		return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
	}

	async function fetchAndRender(p: Period) {
		loading = true;
		empty = false;
		error = null;
		try {
			const data: NewSpeciesEntry[] = await getNewSpeciesTimeline(p);

			if (!data.length) {
				empty = true;
				if (chart) { chart.data.labels = []; chart.data.datasets[0].data = []; chart.update('none'); }
				return;
			}

			const labels = data.map(d => fmtDay(d.day));
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
						label: 'New species',
						data: counts,
						backgroundColor: 'rgba(251,191,36,0.7)',
						borderColor: '#fbbf24',
						borderWidth: 1,
						borderRadius: 3,
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
								label: (ctx) => ` ${ctx.raw} new species`,
							}
						}
					},
					scales: {
						x: {
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: {
								color: '#94a3b8',
								maxRotation: 45,
								autoSkip: true,
								maxTicksLimit: 20,
							}
						},
						y: {
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: { color: '#94a3b8', stepSize: 1 },
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

	$effect(() => { fetchAndRender(period); });

	onDestroy(() => chart?.destroy());
</script>

<div class="bg-slate-900 border border-slate-800 rounded-lg flex flex-col h-64">
	<h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest px-4 pt-3 pb-2 shrink-0">
		New Species First Detected
	</h3>
	<div class="flex-1 relative px-3 pb-3 min-h-0">
		<canvas bind:this={canvas} class="w-full h-full" class:invisible={loading || empty || !!error}></canvas>
		{#if loading}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">Loading…</div>
		{:else if empty}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">No new species in this period.</div>
		{:else if error}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">{error}</div>
		{/if}
	</div>
</div>
