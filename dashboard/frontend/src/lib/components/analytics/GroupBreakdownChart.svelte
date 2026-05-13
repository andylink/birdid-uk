<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getGroupBreakdown, type Period, type GroupBreakdownEntry } from '$lib/api';
	import { groupBadgeColor } from '$lib/bto';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	function truncate(s: string, max = 22): string {
		return s.length > max ? s.slice(0, max - 1) + '…' : s;
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
		empty   = false;
		error   = null;
		try {
			const rows: GroupBreakdownEntry[] = await getGroupBreakdown(p, 15);

			if (!rows.length) {
				empty = true;
				if (chart) { chart.data.labels = []; chart.data.datasets[0].data = []; chart.update('none'); }
				return;
			}

			const labels      = rows.map(r => truncate(r.group_name));
			const counts      = rows.map(r => r.detection_count);
			const barColors   = rows.map(r => groupBadgeColor(r.group_name) + 'bb');
			const borderColors = rows.map(r => groupBadgeColor(r.group_name));

			if (chart) {
				chart.data.labels                             = labels;
				chart.data.datasets[0].data                  = counts;
				(chart.data.datasets[0] as any).backgroundColor = barColors;
				(chart.data.datasets[0] as any).borderColor    = borderColors;
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
						label: 'Detections',
						data: counts,
						backgroundColor: barColors,
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
									const row = rows[ctx.dataIndex];
									return [
										` ${row.detection_count.toLocaleString()} detections`,
										` ${row.species_count} species`,
									];
								}
							}
						}
					},
					scales: {
						x: {
							grid: { color: grid },
							ticks: { color: tick },
							beginAtZero: true,
						},
						y: {
							grid: { display: false },
							ticks: { color: tick, font: { size: 10 } },
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
	title="Top Groups"
	subtitle="Taxonomic groups by detection count"
	height="16rem"
	{loading}
	{empty}
	{error}
	bind:canvasEl={canvas}
/>
