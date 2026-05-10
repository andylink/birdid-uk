<script lang="ts">
	import { getAnalyticsSummary, PERIODS, type Period, type AnalyticsSummary } from '$lib/api';
	import StatCard from '../../components/StatCard.svelte';
	import TopSpeciesChart from '../../components/analytics/TopSpeciesChart.svelte';
	import TimeOfDayChart from '../../components/analytics/TimeOfDayChart.svelte';
	import NewSpeciesChart from '../../components/analytics/NewSpeciesChart.svelte';

	let period = $state<Period>('today');
	let summary = $state<AnalyticsSummary | null>(null);
	let summaryLoading = $state(true);

	$effect(() => {
		const p = period;
		summaryLoading = true;
		summary = null;
		getAnalyticsSummary(p)
			.then(d => { if (period === p) { summary = d; summaryLoading = false; } })
			.catch(() => { summaryLoading = false; });
	});

	function pct(v: number | undefined) {
		return v != null ? `${(v * 100).toFixed(1)}%` : undefined;
	}
</script>

<div class="h-[calc(100vh-3.25rem)] overflow-y-auto">
	<div class="max-w-7xl mx-auto px-6 py-5 space-y-5">

		<!-- Page header + period filter -->
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="text-lg font-semibold text-slate-100 tracking-tight">Analytics</h1>
			<div class="flex text-xs rounded overflow-hidden border border-slate-700">
				{#each PERIODS as p}
					<button
						class="px-3 py-1.5 transition-colors {period === p.value
							? 'bg-emerald-600 text-white'
							: 'text-slate-400 hover:text-slate-200'}"
						onclick={() => period = p.value}
					>
						{p.label}
					</button>
				{/each}
			</div>
		</div>

		<!-- Stat cards -->
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
			<StatCard
				title="Total Detections"
				value={summary?.total_detections.toLocaleString()}
				loading={summaryLoading}
			/>
			<StatCard
				title="Unique Species"
				value={summary?.unique_species}
				loading={summaryLoading}
			/>
			<StatCard
				title="Avg. Confidence"
				value={pct(summary?.avg_confidence)}
				loading={summaryLoading}
			/>
			<StatCard
				title="Most Common"
				value={summary?.most_common_species}
				subtitle={summary ? `${summary.most_common_count.toLocaleString()} detections` : undefined}
				loading={summaryLoading}
			/>
		</div>

		<!-- Charts row: top species + time of day -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
			<TopSpeciesChart {period} />
			<TimeOfDayChart {period} />
		</div>

		<!-- New species chart -->
		<NewSpeciesChart {period} />

	</div>
</div>
