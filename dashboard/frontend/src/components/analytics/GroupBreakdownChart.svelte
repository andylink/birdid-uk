<script lang="ts">
	import { onDestroy } from 'svelte';
	import { getGroupBreakdown, type Period, type GroupBreakdownEntry } from '$lib/api';
	import { groupBadgeColor } from '$lib/bto';

	let { period }: { period: Period } = $props();

	let canvas = $state<HTMLCanvasElement | undefined>(undefined);
	let chart: import('chart.js').Chart | null = null;
	let loading = $state(true);
	let empty = $state(false);
	let error = $state<string | null>(null);

	function truncate(s: string, max = 22): string {
		return s.length > max ? s.slice(0, max - 1) + '…' : s;
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

			const labels     = rows.map(r => truncate(r.group_name));
			const counts     = rows.map(r => r.detection_count);
			const barColors  = rows.map(r => groupBadgeColor(r.group_name) + 'bb');
			const borderColors = rows.map(r => groupBadgeColor(r.group_name));

			if (chart) {
				chart.data.labels                            = labels;
				chart.data.datasets[0].data                 = counts;
				(chart.data.datasets[0] as any).backgroundColor = barColors;
				(chart.data.datasets[0] as any).borderColor    = borderColors;
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
							grid: { color: 'rgba(255,255,255,0.05)' },
							ticks: { color: '#94a3b8' },
							beginAtZero: true,
						},
						y: {
							grid: { display: false },
							ticks: { color: '#94a3b8', font: { size: 10 } },
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
		Top Groups
	</h3>
	<p class="text-[10px] text-slate-600 px-4 pb-1 shrink-0">Taxonomic groups by detection count</p>
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
