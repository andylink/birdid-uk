<script lang="ts">
	import type { Detection } from '$lib/api';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatTime, formatDate } from '$lib/time';
	import Spectrogram from './Spectrogram.svelte';

	let { detection }: { detection: Detection } = $props();

	const time = $derived(formatTime(detection.timestamp));
	const date = $derived(formatDate(detection.timestamp));
	const badgeClass = $derived(confidenceBadgeClass(detection.confidence));
</script>

<article class="flex gap-3 px-4 py-3 border-b border-slate-800 hover:bg-slate-900/50 transition-colors">
	<!-- Confidence bar -->
	<div class="flex flex-col items-center gap-1 pt-0.5">
		<div
			class="w-1 rounded-full bg-slate-700 relative overflow-hidden"
			style="height: 48px"
			aria-label="Confidence {formatConfidence(detection.confidence)}"
		>
			<div
				class="absolute bottom-0 left-0 right-0 bg-emerald-500 rounded-full transition-all"
				style="height: {detection.confidence * 100}%"
			></div>
		</div>
	</div>

	<div class="flex-1 min-w-0">
		<div class="flex items-start justify-between gap-2">
			<div>
				<span class="font-semibold text-slate-100">{detection.species}</span>
				<span class="ml-2 text-xs px-1.5 py-0.5 rounded-full font-mono {badgeClass}">
					{formatConfidence(detection.confidence)}
				</span>
			</div>
			<time class="text-xs text-slate-500 tabular-nums shrink-0" datetime={detection.timestamp}>
				{time}
			</time>
		</div>

		<div class="text-xs text-slate-500 mt-0.5">
			{date}
		</div>

		<!-- Audio player + spectrogram -->
		<Spectrogram filename={detection.filename} species={detection.species} />
	</div>
</article>
