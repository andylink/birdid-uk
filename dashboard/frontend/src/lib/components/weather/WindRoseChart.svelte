<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getWeatherWindRose, type Period, type WeatherWindRoseEntry } from '$lib/api';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty   = $state(false);
	let error   = $state<string | null>(null);

	// Cardinal directions get a slightly brighter colour so they stand out.
	const CARDINAL   = new Set(['N', 'E', 'S', 'W']);
	const COLOR_MAIN = '#818cf8'; // indigo
	const COLOR_CARD = '#a5b4fc'; // lighter indigo for N/E/S/W

	// Read CSS custom properties so chart colours respect the active light/dark theme.
	function chartColors() {
		const s = getComputedStyle(document.documentElement);
		return {
			tick: s.getPropertyValue('--chart-tick').trim() || '#94a3b8',
		};
	}

	// Called whenever a 'themechange' event fires; updates legend label colour.
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
			const data: WeatherWindRoseEntry[] = await getWeatherWindRose(p);
			const total = data.reduce((s, d) => s + d.count, 0);

			if (!total) {
				empty = true;
				if (chart) { chart.data.datasets[0].data = new Array(16).fill(0); chart.update('none'); }
				return;
			}

			const labels = data.map(d => d.direction);
			const counts = data.map(d => d.count);
			const colors = data.map(d =>
				CARDINAL.has(d.direction) ? COLOR_CARD + 'e6' : COLOR_MAIN + 'bf'
			);
			const borders = data.map(d =>
				CARDINAL.has(d.direction) ? COLOR_CARD : COLOR_MAIN
			);

			if (chart) {
				chart.data.labels = labels;
				chart.data.datasets[0].data = counts;
				(chart.data.datasets[0] as any).backgroundColor = colors;
				(chart.data.datasets[0] as any).borderColor     = borders;
				chart.update();
				return;
			}

		if (!canvas) return;

		// Chart.js is imported dynamically to keep it out of the initial bundle.
		const { Chart, PolarAreaController, ArcElement, RadialLinearScale, Tooltip, Legend } =
				await import('chart.js');
			Chart.register(PolarAreaController, ArcElement, RadialLinearScale, Tooltip, Legend);

			const { tick } = chartColors();

			chart = new Chart(canvas, {
				type: 'polarArea',
				data: {
					labels,
					datasets: [{
						label: 'Detections',
						data: counts,
						backgroundColor: colors,
						borderColor: borders,
						borderWidth: 1,
					}],
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					// startAngle offsets sector 0 (N) so it sits at the top
					// (Chart.js PolarArea startAngle is in radians; −π/2 = top).
					startAngle: -Math.PI / 2,
					plugins: {
						legend: {
							position: 'right',
							labels: {
								color: tick,
								font: { size: 10 },
								boxWidth: 10,
								padding: 8,
								// Only show the 8 primary compass points to keep the legend compact.
								filter: (item) =>
									['N','NE','E','SE','S','SW','W','NW'].includes(item.text ?? ''),
							},
						},
						tooltip: {
							callbacks: {
								label: (ctx) => ` ${ctx.raw} detections from ${ctx.label}`,
							},
						},
					},
					scales: {
						r: {
							ticks: {
								color: tick,
								font:  { size: 9 },
								backdropColor: 'transparent',
								maxTicksLimit: 4,
							},
							grid: { color: 'rgba(148,163,184,0.15)' },
						},
					},
				},
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
	title="Wind Direction Rose"
	subtitle="Detections by wind direction (16 compass sectors)"
	{loading}
	{empty}
	{error}
	bind:canvasEl={canvas}
/>
