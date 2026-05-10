<script lang="ts">
	import { onDestroy } from 'svelte';
	import { getBoccTrend, type Period, type BoccTrendEntry } from '$lib/api';
	import { BOCC_COLOR } from '$lib/bto';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	// Ordered BoCC buckets and their chart colours
	const BUCKETS = ['Red', 'Amber', 'Green', 'Unknown'] as const;
	const BUCKET_COLORS: Record<string, { bg: string; border: string }> = {
		Red:     { bg: BOCC_COLOR.Red   + 'bb', border: BOCC_COLOR.Red   },
		Amber:   { bg: BOCC_COLOR.Amber + 'bb', border: BOCC_COLOR.Amber },
		Green:   { bg: BOCC_COLOR.Green + 'bb', border: BOCC_COLOR.Green },
		Unknown: { bg: '#47556999',              border: '#475569'         },
	};

	/** Format YYYY-MM-DD → "09 May" */
	function fmtDay(iso: string): string {
		return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {
			day: '2-digit', month: 'short',
		});
	}

	/** Pivot flat rows into Chart.js stacked-bar datasets. */
	function pivot(rows: BoccTrendEntry[]) {
		// Collect ordered unique days
		const daySet = new Set<string>();
		for (const r of rows) daySet.add(r.day);
		const days = [...daySet].sort();

		// Build a map: day → bocc → count
		const map = new Map<string, Map<string, number>>();
		for (const day of days) map.set(day, new Map());
		for (const r of rows) map.get(r.day)!.set(r.bocc, r.detection_count);

		return {
			labels: days.map(fmtDay),
			datasets: BUCKETS
				.filter(b => rows.some(r => r.bocc === b))  // omit completely empty buckets
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

			const {
				Chart, BarController, BarElement, CategoryScale,
				LinearScale, Tooltip, Legend,
			} = await import('chart.js');
			Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

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
								color: '#94a3b8',
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
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: {
								color: '#94a3b8',
								maxRotation: 45,
								autoSkip: true,
								maxTicksLimit: 20,
							}
						},
						y: {
							stacked: true,
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: { color: '#94a3b8' },
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
	<h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest px-4 pt-3 pb-1 shrink-0">
		Conservation Activity Over Time
	</h3>
	<p class="text-[10px] text-slate-600 px-4 pb-1 shrink-0">Daily detections stacked by BoCC status</p>
	<div class="flex-1 relative px-3 pb-3 min-h-0">
		<canvas bind:this={canvas} class="w-full h-full" class:invisible={loading || empty || !!error}></canvas>
		{#if loading}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">Loading…</div>
		{:else if empty}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">No data for this period.</div>
		{:else if error}
			<div class="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">{error}</div>
		{/if}
	</div>
</div>
