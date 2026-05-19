<script lang="ts">
	import { getAnalyticsSummary, PERIODS, type Period, type AnalyticsSummary } from '$lib/api';
	import StatCard from '$lib/components/StatCard.svelte';
	import TopSpeciesChart from '$lib/components/analytics/TopSpeciesChart.svelte';
	import TimeOfDayChart from '$lib/components/analytics/TimeOfDayChart.svelte';
	import NewSpeciesChart from '$lib/components/analytics/NewSpeciesChart.svelte';
	import BoccBreakdownChart from '$lib/components/analytics/BoccBreakdownChart.svelte';
	import GroupBreakdownChart from '$lib/components/analytics/GroupBreakdownChart.svelte';
	import BoccTrendChart from '$lib/components/analytics/BoccTrendChart.svelte';

	let period = $state<Period>('today');
	let summary = $state<AnalyticsSummary | null>(null);
	let summaryLoading = $state(true);

	// Reload summary whenever the period changes; ignore stale responses.
	$effect(() => {
		const p = period;
		summaryLoading = true;
		summary = null;
		getAnalyticsSummary(p)
			.then(d => { if (period === p) { summary = d; summaryLoading = false; } })
			.catch(() => { summaryLoading = false; });
	});

	// Format a 0–1 ratio as a percentage string, or return undefined if missing.
	function pct(v: number | undefined) {
		return v != null ? `${(v * 100).toFixed(1)}%` : undefined;
	}
</script>

<div class="page-scroll">
	<div class="page-inner">

		<!-- Page header + period filter -->
		<div class="page-header">
			<h1 class="page-title">Analytics</h1>
			<div class="period-group">
				{#each PERIODS as p}
					<button
						class="period-btn"
						class:active={period === p.value}
						onclick={() => (period = p.value)}
					>
						{p.label}
					</button>
				{/each}
			</div>
		</div>

		<!-- Top-level summary stats -->
		<div class="grid-4">
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

		<!-- UK Birds of Conservation Concern (BoCC) stats -->
		<div>
			<h2 class="section-title">Conservation</h2>
			<div class="grid-4">
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

		<div class="grid-2">
			<TopSpeciesChart {period} />
			<TimeOfDayChart {period} />
		</div>

		<div class="grid-2">
			<BoccBreakdownChart {period} />
			<GroupBreakdownChart {period} />
		</div>

		<!-- Full-width trend chart -->
		<BoccTrendChart {period} />

		<NewSpeciesChart {period} />

	</div>
</div>

<style>
	.page-scroll {
		height: calc(100vh - var(--header-height));
		overflow-y: auto;
	}

	.page-inner {
		max-width: 80rem;
		margin: 0 auto;
		padding: 1.25rem 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.page-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.page-title {
		margin: 0;
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--color-text);
		letter-spacing: -0.025em;
	}

	.period-group {
		display: flex;
		font-size: 0.75rem;
		border-radius: 0.375rem;
		overflow: hidden;
		border: 1px solid var(--color-border-strong);
	}

	.period-btn {
		padding: 0.375rem 0.75rem;
		border: none;
		background: transparent;
		cursor: pointer;
		color: var(--color-text-muted);
		transition: color 0.15s, background-color 0.15s;
	}
	.period-btn:hover {
		color: var(--color-text);
	}
	.period-btn.active {
		background: var(--color-accent);
		color: #fff;
	}

	.section-title {
		margin: 0 0 0.75rem;
		font-size: 0.625rem;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	/* 2-up on small screens, 4-up on wide */
	.grid-4 {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1rem;
	}
	@media (min-width: 1024px) {
		.grid-4 {
			grid-template-columns: repeat(4, 1fr);
		}
	}

	/* 1-up on small screens, 2-up on wide */
	.grid-2 {
		display: grid;
		grid-template-columns: 1fr;
		gap: 1rem;
	}
	@media (min-width: 1024px) {
		.grid-2 {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
