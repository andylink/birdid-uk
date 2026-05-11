<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { initTimezone } from '$lib/timezone';
	import { currentTheme, toggleTheme } from '$lib/theme';

	let { children } = $props();

	// Tracks whether dark mode is active — used to render the correct toggle icon.
	let isDark = $state(true);
	// Station name fetched from /api/v1/config; default shown until fetch resolves.
	let stationName = $state('BirdNet-UK');

	onMount(async () => {
		const config = await initTimezone();
		if (config?.station_name) stationName = config.station_name;
		// The inline script in app.html already applied the class; just read it.
		isDark = currentTheme() === 'dark';
	});

	function handleToggle() {
		toggleTheme();
		isDark = currentTheme() === 'dark';
	}
</script>

<div class="min-h-screen bg-slate-100 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col">
	<header class="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 py-3 flex items-center gap-4 shrink-0">
		<a href="/" class="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-semibold text-lg tracking-tight">
			{stationName}
		</a>

		<span class="text-slate-300 dark:text-slate-700">|</span>

		<nav class="flex items-center gap-1 text-sm">
			<a
				href="/"
				class="px-2.5 py-1 rounded transition-colors {$page.url.pathname === '/'
					? 'text-slate-900 dark:text-slate-100 bg-slate-200 dark:bg-slate-800'
					: 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'}"
			>
				Dashboard
			</a>
		<a
			href="/analytics"
			class="px-2.5 py-1 rounded transition-colors {$page.url.pathname.startsWith('/analytics')
				? 'text-slate-900 dark:text-slate-100 bg-slate-200 dark:bg-slate-800'
				: 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'}"
		>
			Analytics
		</a>
		<a
			href="/species"
			class="px-2.5 py-1 rounded transition-colors {$page.url.pathname.startsWith('/species')
				? 'text-slate-900 dark:text-slate-100 bg-slate-200 dark:bg-slate-800'
				: 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'}"
		>
			Species
		</a>
	</nav>

		<div class="ml-auto flex items-center gap-3">
			<span class="text-slate-400 dark:text-slate-600 text-sm">Norfolk garden</span>

			<!-- Light/dark toggle -->
			<button
				onclick={handleToggle}
				class="p-1.5 rounded text-slate-500 dark:text-slate-400
				       hover:text-slate-800 dark:hover:text-slate-200
				       hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
				aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
				title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
			>
				{#if isDark}
					<!-- Moon: currently dark, offer light -->
					<svg viewBox="0 0 24 24" class="w-4 h-4 fill-current" aria-hidden="true">
						<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
					</svg>
				{:else}
					<!-- Sun: currently light, offer dark -->
					<svg viewBox="0 0 24 24" class="w-4 h-4 fill-current" aria-hidden="true">
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

	<main class="flex-1 min-h-0">
		{@render children()}
	</main>
</div>
