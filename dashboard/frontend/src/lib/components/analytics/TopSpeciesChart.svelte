<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getTopSpecies, type Period, type TopSpeciesEntry } from '$lib/api';
	import { groupBadgeColor } from '$lib/bto';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	let entries: TopSpeciesEntry[] = [];

	// Read CSS custom properties so chart colours respect the active light/dark theme.
	function chartColors() {
		const s = getComputedStyle(document.documentElement);
		return {
			grid: s.getPropertyValue('--chart-grid').trim() || 'rgba(255,255,255,0.05)',
			tick: s.getPropertyValue('--chart-tick').trim() || '#94a3b8',
		};
	}

	// Called whenever a 'themechange' event fires; patches scale colours without a full redraw.
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

	function truncate(s: string, max = 28): string {
		return s.length > max ? s.slice(0, max - 1) + '…' : s;
	}

	async function fetchAndRender(p: Period) {
		loading = true;
		empty = false;
		error = null;
		try {
			const data: TopSpeciesEntry[] = await getTopSpecies(p);
			entries = data;

			if (!data.length) {
				empty = true;
				if (chart) { chart.data.labels = []; chart.data.datasets[0].data = []; chart.update('none'); }
				return;
			}

			const labels = data.map(d => truncate(d.species));
			const counts = data.map(d => d.count);
			const colors = data.map(d => groupBadgeColor(d.group_name));
			const borderColors = colors.map(c => c + 'cc');

			if (chart) {
				chart.data.labels = labels;
				chart.data.datasets[0].data = counts;
				(chart.data.datasets[0] as any).backgroundColor = colors.map(c => c + 'bf');
				(chart.data.datasets[0] as any).borderColor = borderColors;
				chart.update();
				return;
			}

		if (!canvas) return;

		// Chart.js is imported dynamically to keep it out of the initial bundle.
		const { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip } =
				await import('chart.js');
			Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

			const { grid, tick } = chartColors();

			chart = new Chart(canvas, {
				type: 'bar',
				data: {
					labels,
					datasets: [{
						label: 'Detections',
						data: counts,
						backgroundColor: colors.map(c => c + 'bf'),
						borderColor: borderColors,
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
							callbacks: {
								label: (ctx) => {
									const entry = entries[ctx.dataIndex];
									const group = entry?.group_name ?? 'Unknown';
									return ` ${ctx.raw} detections · ${group}`;
								}
							}
						}
					},
					scales: {
						x: {
							grid: { color: grid },
							ticks: { color: tick, precision: 0 },
							beginAtZero: true,
						},
						y: {
							grid: { display: false },
							ticks: { color: tick, font: { size: 11 } },
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
	title="Top 10 Species"
	emptyMessage="No detections in this period."
	{loading}
	{empty}
	{error}
	bind:canvasEl={canvas}
/>
