<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getBoccTrend, type Period, type BoccTrendEntry } from '$lib/api';
	import { BOCC_COLOR } from '$lib/bto';
	import ChartCard from '$lib/components/ui/ChartCard.svelte';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	const BUCKETS = ['Red', 'Amber', 'Green', 'Unknown'] as const;
	const BUCKET_COLORS: Record<string, { bg: string; border: string }> = {
		Red:     { bg: BOCC_COLOR.Red   + 'bb', border: BOCC_COLOR.Red   },
		Amber:   { bg: BOCC_COLOR.Amber + 'bb', border: BOCC_COLOR.Amber },
		Green:   { bg: BOCC_COLOR.Green + 'bb', border: BOCC_COLOR.Green },
		Unknown: { bg: '#47556999',              border: '#475569'         },
	};

	// Append T00:00:00 to treat the date as local midnight, not UTC.
	function fmtDay(iso: string): string {
		return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {
			day: '2-digit', month: 'short',
		});
	}

	// Read CSS custom properties so chart colours respect the active light/dark theme.
	function chartColors() {
		const s = getComputedStyle(document.documentElement);
		return {
			grid: s.getPropertyValue('--chart-grid').trim() || 'rgba(255,255,255,0.05)',
			tick: s.getPropertyValue('--chart-tick').trim() || '#94a3b8',
		};
	}

	// Called whenever a 'themechange' event fires; patches scale and legend colours.
	function applyColorsToChart() {
		if (!chart) return;
		const { grid, tick } = chartColors();
		const scales = chart.options.scales as any;
		if (scales?.x?.grid) scales.x.grid.color = grid;
		if (scales?.x?.ticks) scales.x.ticks.color = tick;
		if (scales?.y?.grid) scales.y.grid.color = grid;
		if (scales?.y?.ticks) scales.y.ticks.color = tick;
		const legend = (chart.options.plugins as any)?.legend?.labels;
		if (legend) legend.color = tick;
		chart.update('none');
	}

	// Pivot flat API rows into one dataset per BoCC bucket, filling missing days with 0.
	function pivot(rows: BoccTrendEntry[]) {
		const daySet = new Set<string>();
		for (const r of rows) daySet.add(r.day);
		const days = [...daySet].sort();

		const map = new Map<string, Map<string, number>>();
		for (const day of days) map.set(day, new Map());
		for (const r of rows) map.get(r.day)!.set(r.bocc, r.detection_count);

		return {
			labels: days.map(fmtDay),
			datasets: BUCKETS
				.filter(b => rows.some(r => r.bocc === b))
				.map(b => ({
					label: b,
					data: days.map(d => map.get(d)!.get(b) ?? 0),
					backgroundColor: BUCKET_COLORS[b].bg,
					borderColor:     BUCKET_COLORS[b].border,
					borderWidth: 1,
					stack: 'bocc',
				})),
		};
	}

	async function fetchAndRender(p: Period) {
		loading = true;
		empty   = false;
		error   = null;
		try {
			const rows = await getBoccTrend(p);

			if (!rows.length) {
				empty = true;
				if (chart) {
					chart.data.labels   = [];
					chart.data.datasets = [];
					chart.update('none');
				}
				return;
			}

			const { labels, datasets } = pivot(rows);

			if (chart) {
				chart.data.labels   = labels;
				chart.data.datasets = datasets as any;
				chart.update();
				return;
			}

		if (!canvas) return;

		// Chart.js is imported dynamically to keep it out of the initial bundle.
		const {
			Chart, BarController, BarElement, CategoryScale,
				LinearScale, Tooltip, Legend,
			} = await import('chart.js');
			Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

			const { grid, tick } = chartColors();

			chart = new Chart(canvas, {
				type: 'bar',
				data: { labels, datasets: datasets as any },
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: {
							position: 'top',
							align: 'end',
							labels: {
								color: tick,
								font: { size: 11 },
								boxWidth: 12,
								padding: 12,
							}
						},
						tooltip: {
							mode: 'index',
							callbacks: {
								label: (ctx) => ` ${ctx.dataset.label}: ${(ctx.raw as number).toLocaleString()} detections`,
							}
						}
					},
					scales: {
						x: {
							stacked: true,
							grid: { color: grid },
							ticks: {
								color: tick,
								maxRotation: 45,
								autoSkip: true,
								maxTicksLimit: 20,
							}
						},
						y: {
							stacked: true,
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
	title="Conservation Activity Over Time"
	subtitle="Daily detections stacked by BoCC status"
	height="16rem"
	{loading}
	{empty}
	{error}
	bind:canvasEl={canvas}
/>
