<script lang="ts">
	import { getAnalyticsSummary, PERIODS, type Period, type AnalyticsSummary } from '$lib/api';
	import StatCard from '../../components/StatCard.svelte';
	import TopSpeciesChart from '../../components/analytics/TopSpeciesChart.svelte';
	import TimeOfDayChart from '../../components/analytics/TimeOfDayChart.svelte';
	import NewSpeciesChart from '../../components/analytics/NewSpeciesChart.svelte';
	import BoccBreakdownChart from '../../components/analytics/BoccBreakdownChart.svelte';
	import GroupBreakdownChart from '../../components/analytics/GroupBreakdownChart.svelte';
	import BoccTrendChart from '../../components/analytics/BoccTrendChart.svelte';

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
			<h1 class="text-lg font-semibold text-slate-900 dark:text-slate-100 tracking-tight">Analytics</h1>
			<div class="flex text-xs rounded overflow-hidden border border-slate-300 dark:border-slate-700">
				{#each PERIODS as p}
					<button
						class="px-3 py-1.5 transition-colors {period === p.value
							? 'bg-emerald-600 text-white'
							: 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'}"
						onclick={() => period = p.value}
					>
						{p.label}
					</button>
				{/each}
			</div>
		</div>

		<!-- General stat cards -->
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

		<!-- Conservation stat cards -->
		<div>
			<h2 class="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">
				Conservation
			</h2>
			<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
				<StatCard
					title="Red List Species"
					value={summary?.red_list_species}
					subtitle="UK BoCC Red"
					loading={summaryLoading}
				/>
				<StatCard
					title="Scarce / Rare"
					value={summary?.scarce_rare_species}
					subtitle="Scarce, Rare or Very rare"
					loading={summaryLoading}
				/>
				<StatCard
					title="Groups Represented"
					value={summary?.groups_represented}
					subtitle="Distinct taxonomic groups"
					loading={summaryLoading}
				/>
				<StatCard
					title="Garden Score"
					value={summary?.conservation_score}
					subtitle="Red×3 + Amber×2 + Green×1"
					loading={summaryLoading}
				/>
			</div>
		</div>

		<!-- Charts row: top species + time of day -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
			<TopSpeciesChart {period} />
			<TimeOfDayChart {period} />
		</div>

		<!-- Conservation charts row: BoCC breakdown + group breakdown -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
			<BoccBreakdownChart {period} />
			<GroupBreakdownChart {period} />
		</div>

		<!-- BoCC trend over time (full width) -->
		<BoccTrendChart {period} />

		<!-- New species chart -->
		<NewSpeciesChart {period} />

	</div>
</div>
