<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { createSSE } from '$lib/sse';
	import type { Detection } from '$lib/api';
	import { speciesImageUrl } from '$lib/api';
	import { BOCC_COLOR } from '$lib/bto';
	import { confidenceBadgeClass, formatConfidence } from '$lib/confidence';
	import { formatTime, formatDate } from '$lib/time';
	import DetectionCard from '$lib/components/DetectionCard.svelte';
	import Spectrogram from '$lib/components/Spectrogram.svelte';

	const MAX_ITEMS = 200;

	// ── State ──────────────────────────────────────────────────────────────────
	let detections  = $state<Detection[]>([]);
	let sse: ReturnType<typeof createSSE> | null = null;
	let connected   = $state(false);
	let flashing    = $state(false);
	let soundOn     = $state(false);

	// Notable species seen this session, deduplicated by name
	let notableMap  = $state<Map<string, Detection>>(new Map());
	const notableList = $derived([...notableMap.values()]);

	const latest    = $derived(detections[0] ?? null);

	// Reset the image error flag whenever the detected species changes
	let heroImgError = $state(false);
	$effect(() => {
		if (latest?.species) heroImgError = false;
	});

	function isNotable(d: Detection): boolean {
		return d.uk_bocc === 'Red' || d.species_status === 'Rare' || d.species_status === 'Very rare';
	}

	// ── Audio ──────────────────────────────────────────────────────────────────
	let audioCtx: AudioContext | null = null;

	function getAudioCtx(): AudioContext | null {
		try {
			if (!audioCtx) audioCtx = new AudioContext();
			if (audioCtx.state === 'suspended') audioCtx.resume();
			return audioCtx;
		} catch {
			return null;
		}
	}

	function playChime(notable: boolean) {
		if (!soundOn) return;
		const ctx = getAudioCtx();
		if (!ctx) return;
		// Notable: three-note descending alert   Normal: two-note ascending chime
		const freqs = notable ? [1047, 880, 698] : [880, 1047];
		let t = ctx.currentTime;
		for (const freq of freqs) {
			const osc  = ctx.createOscillator();
			const gain = ctx.createGain();
			osc.connect(gain);
			gain.connect(ctx.destination);
			osc.type = 'sine';
			osc.frequency.value = freq;
			gain.gain.setValueAtTime(0, t);
			gain.gain.linearRampToValueAtTime(notable ? 0.2 : 0.12, t + 0.02);
			gain.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
			osc.start(t);
			osc.stop(t + 0.35);
			t += 0.18;
		}
	}

	function toggleSound() {
		soundOn = !soundOn;
		// Trigger AudioContext creation on this user gesture — required by browsers
		if (soundOn) getAudioCtx();
	}

	// ── Flash ─────────────────────────────────────────────────────────────────
	let flashTimer: ReturnType<typeof setTimeout> | null = null;

	async function triggerFlash() {
		flashing = false;
		await tick(); // force Svelte to remove the class so the animation restarts
		flashing = true;
		if (flashTimer) clearTimeout(flashTimer);
		flashTimer = setTimeout(() => { flashing = false; }, 950);
	}

	// ── SSE ───────────────────────────────────────────────────────────────────
	onMount(() => {
		sse = createSSE('/stream/detections');
		sse.on('detection', (raw) => {
			const d = raw as Detection;
			detections = [d, ...detections].slice(0, MAX_ITEMS);
			connected = true;
			void triggerFlash();
			playChime(isNotable(d));
			if (isNotable(d) && !notableMap.has(d.species)) {
				const next = new Map(notableMap);
				next.set(d.species, d);
				notableMap = next;
			}
		});
	});

	onDestroy(() => {
		sse?.close();
		audioCtx?.close();
		if (flashTimer) clearTimeout(flashTimer);
	});
</script>

<div class="live-page">
<div class="live-inner">

	<!-- ── Page header ── -->
	<header class="live-header">
		<span class="page-title">Live Feed</span>
		<span
			class="live-dot"
			class:connected
			aria-label={connected ? 'Connected' : 'Connecting…'}
		></span>
		{#if detections.length > 0}
			<span class="header-count">
				{detections.length} detection{detections.length !== 1 ? 's' : ''}
			</span>
		{/if}

		<!-- Sound toggle — off by default, user opts in -->
		<button
			class="sound-btn"
			class:sound-on={soundOn}
			onclick={toggleSound}
			title={soundOn ? 'Mute sound alerts' : 'Enable sound alerts'}
			aria-label={soundOn ? 'Mute sound alerts' : 'Enable sound alerts'}
		>
			{#if soundOn}
				<!-- Speaker with sound waves -->
				<svg viewBox="0 0 24 24" class="sound-icon" aria-hidden="true">
					<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
					<path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
					<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
				</svg>
			{:else}
				<!-- Speaker muted (X through speaker) -->
				<svg viewBox="0 0 24 24" class="sound-icon" aria-hidden="true">
					<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
					<line x1="23" y1="9" x2="17" y2="15"/>
					<line x1="17" y1="9" x2="23" y2="15"/>
				</svg>
			{/if}
		</button>
	</header>

	<!-- ── Notable species strip ── -->
	{#if notableList.length > 0}
		<div class="notable-strip">
			<span class="notable-heading">Notable this session</span>
			<div class="notable-pills">
				{#each notableList as d (d.species)}
					{@const label = d.uk_bocc === 'Red' ? 'Red List'
						: d.species_status === 'Very rare' ? 'Very rare' : 'Rare'}
					{@const color = BOCC_COLOR[d.uk_bocc ?? ''] ?? BOCC_COLOR.Red}
					<span
						class="notable-pill"
						style="border-color: {color}44; color: {color}; background-color: {color}11"
						title="{d.species} — {label}"
					>
						<span class="notable-dot" style="background-color: {color}"></span>
						{d.species}
					</span>
				{/each}
			</div>
		</div>
	{/if}

	<!-- ── Hero: latest detection ── -->
	<div
		class="hero-card"
		class:flash={flashing}
		class:notable-hero={latest && isNotable(latest)}
		class:hero-empty={!latest}
	>
		<div class="hero-meta">
			<span class="hero-label">Latest detection</span>
			{#if latest}
				<time class="hero-time tabular" datetime={latest.timestamp}>
					{formatTime(latest.timestamp)} · {formatDate(latest.timestamp)}
				</time>
			{/if}
		</div>

		{#if latest}
			<div class="hero-main-row">
				<div class="hero-text">
					<a
						href="/species/{encodeURIComponent(latest.species)}?from=live"
						class="hero-species"
						class:species-notable={isNotable(latest)}
					>
						{latest.species}
					</a>

					{#if latest.scientific_name}
						<div class="hero-sci">{latest.scientific_name}</div>
					{/if}

					<div class="hero-badges">
						<span class={confidenceBadgeClass(latest.confidence)}>
							{formatConfidence(latest.confidence)}
						</span>
						{#if latest.uk_bocc}
							<span
								class="bocc-badge"
								style="background-color: {BOCC_COLOR[latest.uk_bocc]}22; color: {BOCC_COLOR[latest.uk_bocc]}"
							>
								{latest.uk_bocc} List
							</span>
						{/if}
						{#if latest.species_status}
							<span class="status-badge">{latest.species_status}</span>
						{/if}
					</div>
				</div>

				<!-- Species image — hidden if the backend has no image for this species -->
				{#if !heroImgError}
					<div class="hero-img-col">
						<img
							src={speciesImageUrl(latest.bto_name ?? latest.species)}
							alt={latest.species}
							class="hero-bird-img"
							onerror={() => { heroImgError = true; }}
						/>
					</div>
				{/if}
			</div>

			<Spectrogram filename={latest.filename} species={latest.species} height="6rem" />
		{:else}
			<div class="hero-waiting">
				<svg viewBox="0 0 24 24" class="waiting-icon" aria-hidden="true">
					<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
				</svg>
				<span>Waiting for detections…</span>
			</div>
		{/if}
	</div>

	<!-- ── Scrollable list of previous detections ── -->
	<div class="feed-section">
		<div class="feed-section-header">
			<span>Recent detections</span>
			{#if detections.length > 1}
				<span class="recent-count">{detections.length - 1} more</span>
			{/if}
		</div>
		<div class="feed-list" role="feed" aria-live="polite" aria-label="Previous detections">
			{#if detections.length <= 1}
				<div class="feed-empty">
					<p>More detections will appear here…</p>
				</div>
			{:else}
				{#each detections.slice(1) as detection (detection.id)}
					<DetectionCard
						{detection}
						ondelete={(id) => { detections = detections.filter(d => d.id !== id); }}
					/>
				{/each}
			{/if}
		</div>
	</div>
	</div>
</div>

<style>
	.live-page {
		height: calc(100vh - var(--header-height));
		background: var(--color-page);
		overflow: hidden;
	}
	.live-inner {
		max-width: 80rem;
		margin: 0 auto;
		width: 100%;
		height: 100%;
		display: flex;
		flex-direction: column;
	}

	/* ── Page header ── */
	.live-header {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		padding: 0.5rem 1rem;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface);
		flex-shrink: 0;
	}
	.page-title {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text-2);
	}
	.live-dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 9999px;
		background: var(--color-skeleton-2);
		flex-shrink: 0;
	}
	.live-dot.connected {
		background: #34d399;
		animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}
	.header-count {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}
	/* Sound toggle pushed to the right */
	.sound-btn {
		margin-left: auto;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0.375rem;
		border: none;
		border-radius: 0.375rem;
		background: transparent;
		cursor: pointer;
		color: var(--color-text-dim);
		transition: color 0.15s, background-color 0.15s;
	}
	.sound-btn:hover { color: var(--color-text); background: var(--color-surface-2); }
	.sound-btn.sound-on { color: var(--color-accent-text); }
	.sound-icon {
		width: 1.125rem;
		height: 1.125rem;
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	/* ── Notable strip ── */
	.notable-strip {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		flex-wrap: wrap;
		padding: 0.5rem 1rem;
		border-bottom: 1px solid rgba(239, 68, 68, 0.3);
		background: rgba(239, 68, 68, 0.04);
		flex-shrink: 0;
	}
	.notable-heading {
		font-size: 0.5625rem;
		font-weight: 700;
		color: #ef4444;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		flex-shrink: 0;
	}
	.notable-pills {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem;
	}
	.notable-pill {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		font-size: 0.625rem;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		border: 1px solid;
		font-weight: 500;
	}
	.notable-dot {
		width: 0.375rem;
		height: 0.375rem;
		border-radius: 9999px;
		flex-shrink: 0;
	}

	/* ── Hero card flash animations ── */
	@keyframes flash-normal {
		0%   {
			box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.5);
			background-color: rgba(52, 211, 153, 0.1);
		}
		65%  { box-shadow: 0 0 0 10px rgba(52, 211, 153, 0); }
		100% {
			box-shadow: none;
			background-color: var(--color-surface);
		}
	}
	@keyframes flash-notable {
		0%   {
			box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5);
			background-color: rgba(239, 68, 68, 0.12);
		}
		65%  { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
		100% {
			box-shadow: none;
			background-color: rgba(239, 68, 68, 0.04);
		}
	}

	/* ── Hero card ── */
	.hero-card {
		flex-shrink: 0;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface);
	}
	.hero-card.flash {
		animation: flash-normal 0.95s ease-out forwards;
	}
	.hero-card.notable-hero {
		border-left: 3px solid #ef4444;
		background: rgba(239, 68, 68, 0.04);
	}
	.hero-card.notable-hero.flash {
		animation: flash-notable 0.95s ease-out forwards;
	}
	/* When no detection yet, let the card grow to fill space */
	.hero-card.hero-empty {
		flex: 1;
		display: flex;
		flex-direction: column;
	}

	.hero-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 0.625rem;
	}
	.hero-label {
		font-size: 0.5625rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-text-muted);
	}
	.hero-time {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}

	.hero-species {
		display: block;
		font-size: 1.75rem;
		font-weight: 700;
		color: var(--color-text);
		text-decoration: none;
		line-height: 1.15;
		margin-bottom: 0.25rem;
		transition: color 0.15s;
	}
	.hero-species:hover { color: var(--color-accent-text); text-decoration: underline; }
	.hero-species.species-notable { color: #ef4444; }

	/* Row: text on left, species photo on right */
	.hero-main-row {
		display: flex;
		gap: 0.875rem;
		align-items: flex-start;
		margin-bottom: 0.875rem;
	}
	.hero-text {
		flex: 1;
		min-width: 0;
	}
	.hero-img-col {
		flex-shrink: 0;
		width: 5.5rem;
		height: 5.5rem;
		border-radius: 0.375rem;
		overflow: hidden;
		background: var(--color-skeleton);
	}
	.hero-bird-img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.hero-sci {
		font-size: 0.875rem;
		color: var(--color-text-muted);
		font-style: italic;
		margin-bottom: 0.75rem;
	}
	.hero-badges {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		flex-wrap: wrap;
		margin-bottom: 0.875rem;
	}
	.bocc-badge {
		font-size: 0.5625rem;
		font-weight: 700;
		padding: 0.125rem 0.4rem;
		border-radius: 0.25rem;
	}
	.status-badge {
		font-size: 0.5625rem;
		font-weight: 600;
		padding: 0.125rem 0.4rem;
		border-radius: 0.25rem;
		background: var(--color-skeleton);
		color: var(--color-text-muted);
	}

	.hero-waiting {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		flex: 1;
		gap: 0.875rem;
		color: var(--color-text-ghost);
		padding: 2rem 0;
	}
	.waiting-icon {
		width: 3rem;
		height: 3rem;
		fill: currentColor;
		opacity: 0.3;
	}
	.hero-waiting span {
		font-size: 0.9375rem;
	}

	/* ── Feed section ── */
	.feed-section {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.feed-section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.3125rem 1rem;
		font-size: 0.5625rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-text-muted);
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}
	.recent-count {
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
		font-size: 0.6875rem;
	}
	.feed-list {
		flex: 1;
		overflow-y: auto;
	}
	.feed-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 2rem 1rem;
		color: var(--color-text-ghost);
	}
	.feed-empty p { margin: 0; font-size: 0.875rem; }
</style>
