<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getWeatherByTemperature, type Period, type WeatherTempEntry } from '$lib/api';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty   = $state(false);
	let error   = $state<string | null>(null);

	// Cool blue at freezing → green at UK optimum (5–15°C) → warm orange above 20°C.
	const BIN_COLORS: Record<string, string> = {
		sub_zero:       '#818cf8', // indigo  — freezing
		zero_five:      '#60a5fa', // blue    — cold
		five_ten:       '#34d399', // emerald — cool
		ten_fifteen:    '#4ade80', // green   — mild (UK optimum)
		fifteen_twenty: '#facc15', // yellow  — warm
		above_twenty:   '#fb923c', // orange  — hot
	};

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
		if (scales?.x?.grid)  scales.x.grid.color  = grid;
		if (scales?.x?.ticks) scales.x.ticks.color = tick;
		if (scales?.y?.grid)  scales.y.grid.color  = grid;
		if (scales?.y?.ticks) scales.y.ticks.color = tick;
		chart.update('none');
	}

	async function fetchAndRender(p: Period) {
		loading = true;
		empty   = false;
		error   = null;
		try {
			const data: WeatherTempEntry[] = await getWeatherByTemperature(p);
			const total = data.reduce((s, d) => s + d.count, 0);

			if (!total) {
				empty = true;
				if (chart) { chart.data.datasets[0].data = new Array(6).fill(0); chart.update('none'); }
				return;
			}

			const labels = data.map(d => d.label);
			const counts = data.map(d => d.count);
			const colors = data.map(d => BIN_COLORS[d.bin] ?? '#94a3b8');

			if (chart) {
				chart.data.labels = labels;
				chart.data.datasets[0].data = counts;
				(chart.data.datasets[0] as any).backgroundColor = colors.map(c => c + 'bf');
				(chart.data.datasets[0] as any).borderColor     = colors;
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
						borderColor: colors,
						borderWidth: 1,
						borderRadius: 3,
					}],
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { display: false },
						tooltip: {
							callbacks: {
								label: (ctx) => ` ${ctx.raw} detections`,
							},
						},
					},
					scales: {
						x: {
							grid:  { display: false },
							ticks: { color: tick, font: { size: 11 } },
						},
						y: {
							grid:  { color: grid },
							ticks: { color: tick, precision: 0 },
							beginAtZero: true,
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
	title="Detections by Temperature"
	subtitle="Air temperature at detection time (°C)"
	{loading}
	{empty}
	{error}
	bind:canvasEl={canvas}
/>
