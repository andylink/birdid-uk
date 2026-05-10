<script lang="ts">
	/**
	 * Spectrogram.svelte — inline spectrogram image + audio player.
	 *
	 * Uses /spectrogram/{filename} and /audio/{filename} since the dashboard
	 * serves media by filename (basename of clip_path), not by detection ID.
	 */

	let {
		filename,
		species
	}: {
		filename: string | null;
		species: string;
	} = $props();

	let imgLoaded = $state(false);
	let imgError = $state(false);

	function onImgLoad() { imgLoaded = true; }
	function onImgError() { imgError = true; }
</script>

{#if filename}
	<div class="mt-2 flex flex-col gap-1.5">

		<!-- Spectrogram image with loading skeleton + error fallback -->
		{#if !imgError}
			<div class="relative h-12 rounded overflow-hidden bg-slate-800">
				{#if !imgLoaded}
					<div class="absolute inset-0 bg-slate-700 animate-pulse" aria-hidden="true"></div>
				{/if}
				<img
					src="/spectrogram/{filename}"
					alt="Spectrogram for {species}"
					class="h-full w-full object-cover transition-opacity duration-200
					       {imgLoaded ? 'opacity-100' : 'opacity-0'}"
					loading="lazy"
					onload={onImgLoad}
					onerror={onImgError}
				/>
			</div>
		{/if}

		<!-- Audio player -->
		<audio
			src="/audio/{filename}"
			controls
			preload="none"
			class="w-full h-8"
			aria-label="Audio clip for {species}"
		></audio>

	</div>
{/if}
