<script lang="ts">
	import SpeciesHeatmap from '$lib/components/SpeciesHeatmap.svelte';
	import DetectionFeed from '$lib/components/DetectionFeed.svelte';
	import ActivityChart from '$lib/components/ActivityChart.svelte';
</script>

<div class="page-shell">
	<div class="top-row">
		<div class="heatmap-panel">
			<SpeciesHeatmap />
		</div>
		<div class="feed-panel">
			<DetectionFeed />
		</div>
	</div>
	<div class="activity-bar">
		<ActivityChart />
	</div>
</div>

<style>
	.page-shell {
		display: flex;
		flex-direction: column;
		height: calc(100vh - var(--header-height));
	}

	.top-row {
		display: flex;
		flex: 1;
		min-height: 0;
	}

	.heatmap-panel {
		flex: 1;
		min-width: 0;
		border-right: 1px solid var(--color-border);
	}

	.feed-panel {
		width: 20rem;
		flex-shrink: 0;
		border-left: 1px solid var(--color-border);
	}

	.activity-bar {
		height: 10rem;
		flex-shrink: 0;
		border-top: 1px solid var(--color-border);
		background: color-mix(in srgb, var(--color-surface) 40%, transparent);
	}
</style>
