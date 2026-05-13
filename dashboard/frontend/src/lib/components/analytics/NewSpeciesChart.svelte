<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getNewSpeciesTimeline, type Period, type NewSpeciesEntry } from '$lib/api';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	function fmtDay(iso: string): string {
		const d = new Date(iso + 'T00:00:00');
		return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
	}

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

			const { grid, tick } = chartColors();

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
							grid: { color: grid },
							ticks: {
								color: tick,
								maxRotation: 45,
								autoSkip: true,
								maxTicksLimit: 20,
							}
						},
						y: {
							grid: { color: grid },
							ticks: { color: tick, stepSize: 1 },
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

	onMount(() => {
		document.addEventListener('themechange', applyColorsToChart);
		return () => document.removeEventListener('themechange', applyColorsToChart);
	});

	onDestroy(() => chart?.destroy());
</script>

<ChartCard
	title="New Species First Detected"
	height="16rem"
	emptyMessage="No new species in this period."
	{loading}
	{empty}
	{error}
	bind:canvasEl={canvas}
/>
