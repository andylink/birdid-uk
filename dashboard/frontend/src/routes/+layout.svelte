<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { initTimezone } from '$lib/timezone';
	import { currentTheme, toggleTheme } from '$lib/theme';

	let { children } = $props();

	let isDark = $state(true);
	let stationName = $state('BirdNet-UK');

	onMount(async () => {
		// Fetch station config; use the station name if provided.
		const config = await initTimezone();
		if (config?.station_name) stationName = config.station_name;
		isDark = currentTheme() === 'dark';
	});

	function handleToggle() {
		toggleTheme();
		isDark = currentTheme() === 'dark';
	}
</script>

<div class="shell">
	<header class="header">
		<a href="/" class="brand">{stationName}</a>

		<span class="divider" aria-hidden="true">|</span>

		<nav class="nav" aria-label="Main navigation">
			<a
				href="/"
				class="nav-link"
				aria-current={$page.url.pathname === '/' ? 'page' : undefined}
			>
				Dashboard
			</a>
			<a
				href="/analytics"
				class="nav-link"
				aria-current={$page.url.pathname.startsWith('/analytics') ? 'page' : undefined}
			>
				Analytics
			</a>
			<a
				href="/weather"
				class="nav-link"
				aria-current={$page.url.pathname.startsWith('/weather') ? 'page' : undefined}
			>
				Weather
			</a>
			<a
				href="/species"
				class="nav-link"
				aria-current={$page.url.pathname.startsWith('/species') ? 'page' : undefined}
			>
				Species
			</a>
		</nav>

		<div class="header-end">
			<span class="location-hint">Norfolk garden</span>

			<button
				onclick={handleToggle}
				class="theme-btn"
				aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
				title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
			>
				{#if isDark}
					<!-- Moon icon (dark mode active) -->
					<svg viewBox="0 0 24 24" class="theme-icon" aria-hidden="true">
						<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
					</svg>
				{:else}
					<!-- Sun icon (light mode active) -->
					<svg viewBox="0 0 24 24" class="theme-icon" aria-hidden="true">
						<circle cx="12" cy="12" r="5"/>
						<line x1="12" y1="1" x2="12" y2="3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
						<line x1="12" y1="21" x2="12" y2="23" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
						<line x1="4.22" y1="4.22" x2="5.64" y2="5.64" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
						<line x1="18.36" y1="18.36" x2="19.78" y2="19.78" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
						<line x1="1" y1="12" x2="3" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
						<line x1="21" y1="12" x2="23" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
						<line x1="4.22" y1="19.78" x2="5.64" y2="18.36" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
						<line x1="18.36" y1="5.64" x2="19.78" y2="4.22" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
					</svg>
				{/if}
			</button>
		</div>
	</header>

	<main class="main">
		{@render children()}
	</main>
</div>

<style>
	.shell {
		min-height: 100vh;
		background: var(--color-page);
		color: var(--color-text);
		display: flex;
		flex-direction: column;
	}

	.header {
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border);
		padding: 0 1rem;
		height: var(--header-height);
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-shrink: 0;
	}

	.brand {
		color: var(--color-accent);
		font-weight: 600;
		font-size: 1.125rem;
		letter-spacing: -0.025em;
		text-decoration: none;
	}

	.divider {
		color: var(--color-border-strong);
	}

	.nav {
		display: flex;
		align-items: center;
		gap: 0.25rem;
	}

	.nav-link {
		padding: 0.25rem 0.625rem;
		border-radius: 0.375rem;
		font-size: 0.875rem;
		text-decoration: none;
		color: var(--color-text-muted);
		transition: color 0.15s, background-color 0.15s;
	}
	.nav-link:hover {
		color: var(--color-text);
	}
	.nav-link[aria-current="page"] {
		color: var(--color-text);
		background: var(--color-surface-2);
	}

	/* Push theme toggle and location hint to the right */
	.header-end {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.location-hint {
		font-size: 0.875rem;
		color: var(--color-text-dim);
	}

	.theme-btn {
		padding: 0.375rem;
		border-radius: 0.375rem;
		border: none;
		background: transparent;
		cursor: pointer;
		color: var(--color-text-muted);
		transition: color 0.15s, background-color 0.15s;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.theme-btn:hover {
		color: var(--color-text);
		background: var(--color-surface-2);
	}

	.theme-icon {
		width: 1rem;
		height: 1rem;
		fill: currentColor;
	}

	/* Takes up remaining vertical space below the header */
	.main {
		flex: 1;
		min-height: 0;
	}
</style>
