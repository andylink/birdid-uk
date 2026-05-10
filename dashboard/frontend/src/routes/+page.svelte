<script lang="ts">
	import SpeciesHeatmap from '../components/SpeciesHeatmap.svelte';
	import DetectionFeed from '../components/DetectionFeed.svelte';
	import ActivityChart from '../components/ActivityChart.svelte';
</script>

<!--
  Three-panel layout:
    • SpeciesHeatmap  — flex-1, scrollable table
    • DetectionFeed   — w-80, right sidebar
    • ActivityChart   — h-40, bottom bar (full width)
-->
<div class="flex flex-col h-[calc(100vh-3.25rem)]">

	<!-- Top row: heatmap + feed -->
	<div class="flex flex-1 min-h-0">

		<!-- Heatmap: takes all remaining width -->
		<div class="flex-1 min-w-0 border-r border-slate-800">
			<SpeciesHeatmap />
		</div>

		<!-- Detection feed sidebar -->
		<div class="w-80 shrink-0 border-l border-slate-800">
			<DetectionFeed />
		</div>

	</div>

	<!-- Bottom bar: activity chart -->
	<div class="h-40 shrink-0 border-t border-slate-800 bg-slate-900/40">
		<ActivityChart />
	</div>

</div>
