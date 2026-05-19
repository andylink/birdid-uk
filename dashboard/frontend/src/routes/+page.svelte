<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import SpeciesHeatmap from '$lib/components/SpeciesHeatmap.svelte';
	import DetectionFeed from '$lib/components/DetectionFeed.svelte';
	import ActivityChart from '$lib/components/ActivityChart.svelte';

	// On small screens the dashboard layout breaks — redirect to the dedicated Live Feed page
	onMount(() => {
		if (window.matchMedia('(max-width: 900px)').matches) {
			goto('/live', { replaceState: true });
		}
	});
</script>

<svelte:head>
	<title>Detections — Bird Detector</title>
</svelte:head>

<div class="page-shell">
	<div class="top-row">
		<!-- Heatmap fills the remaining width; feed is a fixed-width sidebar -->
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
	/* Full-height layout: top row takes available space, activity bar is fixed height */
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
