<script lang="ts">
	import {
		getWeatherStatus,
		getWeatherSummary,
		PERIODS,
		type Period,
		type WeatherStatus,
		type WeatherSummary,
	} from '$lib/api';
	import StatCard from '$lib/components/StatCard.svelte';
	import WeatherConditionChart from '$lib/components/weather/WeatherConditionChart.svelte';
	import WindSpeedChart from '$lib/components/weather/WindSpeedChart.svelte';
	import TemperatureChart from '$lib/components/weather/TemperatureChart.svelte';
	import WindRoseChart from '$lib/components/weather/WindRoseChart.svelte';

	let period  = $state<Period>('30d');
	let status  = $state<WeatherStatus | null>(null);
	let summary = $state<WeatherSummary | null>(null);
	let loading = $state(true);
	let error   = $state<string | null>(null);

	// Stale-response guard: discard results from a superseded period selection.
	$effect(() => {
		const p = period;
		loading = true;
		error   = null;
		status  = null;
		summary = null;

		Promise.all([getWeatherStatus(p), getWeatherSummary(p)])
			.then(([s, w]) => {
				if (period !== p) return;
				status  = s;
				summary = w;
			})
			.catch(() => {
				if (period === p) error = 'Failed to load weather data. Please refresh.';
			})
			.finally(() => { if (period === p) loading = false; });
	});

	// Format a nullable number as a fixed-decimal string with unit, or return undefined for StatCard.
	function fmt(v: number | null | undefined, unit: string, dp = 1): string | undefined {
		return v != null ? `${v.toFixed(dp)}${unit}` : undefined;
	}

	function coverageLabel(s: WeatherStatus): string {
		return `${s.coverage_pct}% of ${s.total_detections.toLocaleString()} detections`;
	}
</script>

<svelte:head>
	<title>Weather — Bird Detector</title>
</svelte:head>

<div class="page-scroll">
	<div class="page-inner">

		<!-- Header + period selector -->
		<div class="page-header">
			<h1 class="page-title">Weather</h1>
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

		<!-- Error state -->
		{#if error}
			<p class="fetch-error">{error}</p>

		<!-- No weather data state -->
		{:else if !loading && status && status.with_weather === 0}
			<div class="info-card">
				<div class="info-icon">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<path d="M2.5 19h19M15.25 5.75a3.25 3.25 0 1 0-6.5 0c0 1.5.75 2.5 1.25 3.25H8.5A3.5 3.5 0 0 0 5 12.5v.25a2.25 2.25 0 0 0 2.25 2.25h9.5A2.25 2.25 0 0 0 19 12.75V12.5A3.5 3.5 0 0 0 15.5 9h-1.5c.5-.75 1.25-1.75 1.25-3.25z"/>
					</svg>
				</div>
				<div class="info-text">
					<p class="info-title">No weather data collected yet</p>
					<p class="info-body">
						Enable weather metadata by adding the following to <code>config.toml</code>:
					</p>
					<pre class="info-code">[weather]
enabled  = true
provider = "open_meteo"   # free, no key required</pre>
					<p class="info-body">
						Once enabled, each detection will be tagged with temperature, wind, pressure
						and sky conditions from the configured provider.
					</p>
				</div>
			</div>

		<!-- Data present -->
		{:else}

			<!-- Partial coverage notice -->
			{#if status && status.coverage_pct > 0 && status.coverage_pct < 100}
				<div class="coverage-notice">
					Weather coverage: <strong>{status.coverage_pct}%</strong> of detections in this period
					have weather data — recorded since weather was first enabled.
				</div>
			{/if}

			<!-- Stat cards -->
			<div class="grid-4">
				<StatCard
					title="Avg Temperature"
					value={fmt(summary?.avg_temp, '°C')}
					loading={loading}
				/>
				<StatCard
					title="Avg Wind Speed"
					value={fmt(summary?.avg_wind_speed, ' m/s')}
					loading={loading}
				/>
				<StatCard
					title="Most Common Condition"
					value={summary?.most_common_condition ?? undefined}
					loading={loading}
				/>
				<StatCard
					title="Weather Coverage"
					value={status ? coverageLabel(status) : undefined}
					loading={loading}
				/>
			</div>

			<!-- Charts row 1 -->
			<div class="grid-2">
				<WeatherConditionChart {period} />
				<WindSpeedChart {period} />
			</div>

			<!-- Charts row 2 -->
			<div class="grid-2">
				<TemperatureChart {period} />
				<WindRoseChart {period} />
			</div>

		{/if}

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
	.period-btn:hover { color: var(--color-text); }
	.period-btn.active {
		background: var(--color-accent);
		color: #fff;
	}

	/* Error message */
	.fetch-error {
		margin: 0;
		padding: 0.75rem 1rem;
		background: color-mix(in srgb, var(--color-danger, #ef4444) 10%, transparent);
		border: 1px solid color-mix(in srgb, var(--color-danger, #ef4444) 30%, transparent);
		border-radius: 0.375rem;
		color: var(--color-danger, #ef4444);
		font-size: 0.875rem;
	}

	/* No-data info card */
	.info-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		padding: 2rem;
		display: flex;
		gap: 1.5rem;
		align-items: flex-start;
	}

	.info-icon {
		flex-shrink: 0;
		width: 2.5rem;
		height: 2.5rem;
		color: var(--color-text-muted);
	}
	.info-icon svg {
		width: 100%;
		height: 100%;
	}

	.info-text {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.info-title {
		margin: 0;
		font-size: 0.9375rem;
		font-weight: 600;
		color: var(--color-text);
	}

	.info-body {
		margin: 0;
		font-size: 0.875rem;
		color: var(--color-text-muted);
		line-height: 1.5;
	}

	.info-code {
		margin: 0;
		padding: 0.75rem 1rem;
		background: var(--color-page);
		border: 1px solid var(--color-border);
		border-radius: 0.375rem;
		font-size: 0.8125rem;
		color: var(--color-text);
		white-space: pre;
		overflow-x: auto;
	}

	/* Partial coverage notice */
	.coverage-notice {
		padding: 0.625rem 1rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-left: 3px solid var(--color-accent);
		border-radius: 0.375rem;
		font-size: 0.8125rem;
		color: var(--color-text-muted);
	}

	/* Grids — match analytics page */
	.grid-4 {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1rem;
	}
	@media (min-width: 1024px) {
		.grid-4 { grid-template-columns: repeat(4, 1fr); }
	}

	.grid-2 {
		display: grid;
		grid-template-columns: 1fr;
		gap: 1rem;
	}
	@media (min-width: 1024px) {
		.grid-2 { grid-template-columns: repeat(2, 1fr); }
	}
</style>
