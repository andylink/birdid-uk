<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getByHour, type Period } from '$lib/api';
	import { localToday } from '$lib/time';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let error = $state<string | null>(null);

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

	async function fetchAndRender(p: Period) {
		loading = true;
		error = null;
		try {
			const hourly = p === 'today'
				? await getByHour(localToday())
				: await getByHour(undefined, p);

			if (chart) {
				chart.data.datasets[0].data = hourly.data;
				chart.update();
				return;
			}

		if (!canvas) return;

		// Chart.js is imported dynamically to keep it out of the initial bundle.
		const { Chart, LineController, LineElement, LinearScale, CategoryScale,
				PointElement, Tooltip, Filler } = await import('chart.js');
			Chart.register(LineController, LineElement, LinearScale, CategoryScale,
				PointElement, Tooltip, Filler);

			const { grid, tick } = chartColors();

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
							grid: { color: grid },
					ticks: {
							color: tick,
							// Show every third hour label to avoid overlap on narrow cards.
							maxTicksLimit: 8,
							callback: (_val, idx) => idx % 3 === 0 ? hourly.labels[idx] : '',
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
	title="Detections by Time of Day"
	{loading}
	{error}
	bind:canvasEl={canvas}
/>
