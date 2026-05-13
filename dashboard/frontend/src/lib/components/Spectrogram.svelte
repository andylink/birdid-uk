<script lang="ts">
	/**
	 * Spectrogram.svelte — inline spectrogram image + audio player.
	 *
	 * Uses /spectrogram/{filename} and /audio/{filename} since the dashboard
	 * serves media by filename (basename of clip_path), not by detection ID.
	 */

	let {
		filename,
		species,
	}: {
		filename: string | null;
		species: string;
	} = $props();

	let imgLoaded = $state(false);
	let imgError  = $state(false);

	function onImgLoad()  { imgLoaded = true; }
	function onImgError() { imgError  = true; }
</script>

{#if filename}
	<div class="spectrogram-wrap">
		<!-- Spectrogram image with loading skeleton + error fallback -->
		{#if !imgError}
			<div class="spec-img-box">
				{#if !imgLoaded}
					<div class="spec-skeleton skeleton-pulse" aria-hidden="true"></div>
				{/if}
				<img
					src="/spectrogram/{filename}"
					alt="Spectrogram for {species}"
					class="spec-img"
					class:loaded={imgLoaded}
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
			class="audio-player"
			aria-label="Audio clip for {species}"
		></audio>
	</div>
{/if}

<style>
	.spectrogram-wrap {
		margin-top: 0.5rem;
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.spec-img-box {
		position: relative;
		height: 3rem;
		border-radius: 0.25rem;
		overflow: hidden;
		background: var(--color-skeleton);
	}

	.spec-skeleton {
		position: absolute;
		inset: 0;
		background: var(--color-skeleton-2);
	}

	.spec-img {
		height: 100%;
		width: 100%;
		object-fit: cover;
		opacity: 0;
		transition: opacity 0.2s;
	}
	.spec-img.loaded {
		opacity: 1;
	}

	.audio-player {
		width: 100%;
		height: 2rem;
	}
</style>
