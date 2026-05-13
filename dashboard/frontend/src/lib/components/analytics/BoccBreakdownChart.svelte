<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getBoccBreakdown, type Period, type BoccBreakdownEntry } from '$lib/api';
	import { BOCC_COLOR } from '$lib/bto';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);
	let data = $state<BoccBreakdownEntry[]>([]);

	const BOCC_CHART_COLOR: Record<string, string> = {
		Red:     BOCC_COLOR.Red,
		Amber:   BOCC_COLOR.Amber,
		Green:   BOCC_COLOR.Green,
		Unknown: '#475569',
	};

	function chartColors() {
		const s = getComputedStyle(document.documentElement);
		return {
			grid: s.getPropertyValue('--chart-grid').trim() || 'rgba(255,255,255,0.05)',
			tick: s.getPropertyValue('--chart-tick').trim() || '#94a3b8',
		};
	}

	function applyColorsToChart() {
		if (!chart) return;
		const { tick } = chartColors();
		const legend = (chart.options.plugins as any)?.legend?.labels;
		if (legend) legend.color = tick;
		chart.update('none');
	}

	async function fetchAndRender(p: Period) {
		loading = true;
		empty   = false;
		error   = null;
		try {
			const rows = await getBoccBreakdown(p);
			data = rows;

			if (!rows.length || rows.every(r => r.species_count === 0)) {
				empty = true;
				if (chart) { chart.data.labels = []; chart.data.datasets[0].data = []; chart.update('none'); }
				return;
			}

			const labels  = rows.map(r => r.bocc);
			const counts  = rows.map(r => r.species_count);
			const colors  = rows.map(r => BOCC_CHART_COLOR[r.bocc] ?? '#475569');
			const borders = colors.map(c => c);

			if (chart) {
				chart.data.labels                             = labels;
				chart.data.datasets[0].data                  = counts;
				(chart.data.datasets[0] as any).backgroundColor = colors;
				(chart.data.datasets[0] as any).borderColor     = borders;
				chart.update();
				return;
			}

			if (!canvas) return;

			const { Chart, DoughnutController, ArcElement, Tooltip, Legend } =
				await import('chart.js');
			Chart.register(DoughnutController, ArcElement, Tooltip, Legend);

			const { tick } = chartColors();

			chart = new Chart(canvas, {
				type: 'doughnut',
				data: {
					labels,
					datasets: [{
						label: 'Species',
						data: counts,
						backgroundColor: colors.map(c => c + 'cc'),
						borderColor: colors,
						borderWidth: 2,
						hoverOffset: 6,
					}]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					cutout: '62%',
					plugins: {
						legend: {
							position: 'right',
							labels: {
								color: tick,
								font: { size: 11 },
								boxWidth: 12,
								padding: 12,
							}
						},
						tooltip: {
							callbacks: {
								label: (ctx) => {
									const row = rows[ctx.dataIndex];
									return [
										` ${row.species_count} species`,
										` ${row.detection_count.toLocaleString()} detections`,
									];
								}
							}
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
	title="BoCC Status Breakdown"
	subtitle="Unique species by conservation list"
	height="16rem"
	{loading}
	{empty}
	{error}
	bind:canvasEl={canvas}
/>
