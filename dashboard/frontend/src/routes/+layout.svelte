<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { initTimezone } from '$lib/timezone';
	import { currentTheme, toggleTheme } from '$lib/theme';
	import { auth, checkAuth } from '$lib/auth';

	let { children } = $props();

	let isDark = $state(true);
	let stationName = $state('BirdNet-UK');
	let menuOpen = $state(false);

	onMount(async () => {
		const config = await initTimezone();
		if (config?.station_name) stationName = config.station_name;
		isDark = currentTheme() === 'dark';
		await checkAuth();
	});

	function handleToggle() {
		toggleTheme();
		isDark = currentTheme() === 'dark';
	}

	function closeMenu() {
		menuOpen = false;
	}

	// Close menu whenever the route changes
	$effect(() => {
		$page.url.pathname;
		menuOpen = false;
	});
</script>

<div class="shell">
	<header class="header">
		<a href="/" class="brand">{stationName}</a>

		<span class="divider" aria-hidden="true">|</span>

		<!-- Full nav — hidden on small screens -->
		<nav class="nav" aria-label="Main navigation">
			<a
				href="/"
				class="nav-link dashboard-link"
				aria-current={$page.url.pathname === '/' ? 'page' : undefined}
			>
				Dashboard
			</a>
			<a
				href="/live"
				class="nav-link nav-link-live"
				aria-current={$page.url.pathname === '/live' ? 'page' : undefined}
			>
				<span class="nav-live-dot" aria-hidden="true"></span>
				Live
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
			{#if $auth.authenticated}
				<a
					href="/admin"
					class="nav-link nav-link-admin"
					aria-current={$page.url.pathname.startsWith('/admin') ? 'page' : undefined}
				>
					Admin
				</a>
			{:else if $auth.checked}
				<a
					href="/login"
					class="nav-link nav-link-login"
					aria-current={$page.url.pathname === '/login' ? 'page' : undefined}
				>
					Login
				</a>
			{/if}
		</nav>

		<div class="header-end">
			<button
				onclick={handleToggle}
				class="theme-btn"
				aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
				title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
			>
				{#if isDark}
					<svg viewBox="0 0 24 24" class="theme-icon" aria-hidden="true">
						<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
					</svg>
				{:else}
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

			<!-- Hamburger — only on small screens -->
			<button
				class="menu-btn"
				onclick={() => (menuOpen = !menuOpen)}
				aria-label={menuOpen ? 'Close navigation' : 'Open navigation'}
				aria-expanded={menuOpen}
				aria-controls="nav-drawer"
			>
				{#if menuOpen}
					<!-- X icon -->
					<svg viewBox="0 0 24 24" class="menu-icon" aria-hidden="true">
						<line x1="18" y1="6" x2="6" y2="18"/>
						<line x1="6" y1="6" x2="18" y2="18"/>
					</svg>
				{:else}
					<!-- Hamburger icon -->
					<svg viewBox="0 0 24 24" class="menu-icon" aria-hidden="true">
						<line x1="3" y1="6"  x2="21" y2="6"/>
						<line x1="3" y1="12" x2="21" y2="12"/>
						<line x1="3" y1="18" x2="21" y2="18"/>
					</svg>
				{/if}
			</button>
		</div>
	</header>

	<!-- Dropdown drawer (small screens only) -->
	{#if menuOpen}
		<!-- Backdrop: clicking outside the drawer closes it -->
		<div class="nav-backdrop" onclick={closeMenu} aria-hidden="true"></div>
		<nav id="nav-drawer" class="nav-drawer" aria-label="Main navigation">
			<a
				href="/"
				class="drawer-link dashboard-link"
				aria-current={$page.url.pathname === '/' ? 'page' : undefined}
				onclick={closeMenu}
			>
				Dashboard
			</a>
			<a
				href="/live"
				class="drawer-link drawer-link-live"
				aria-current={$page.url.pathname === '/live' ? 'page' : undefined}
				onclick={closeMenu}
			>
				<span class="nav-live-dot" aria-hidden="true"></span>
				Live
			</a>
			<a
				href="/analytics"
				class="drawer-link"
				aria-current={$page.url.pathname.startsWith('/analytics') ? 'page' : undefined}
				onclick={closeMenu}
			>
				Analytics
			</a>
			<a
				href="/weather"
				class="drawer-link"
				aria-current={$page.url.pathname.startsWith('/weather') ? 'page' : undefined}
				onclick={closeMenu}
			>
				Weather
			</a>
			<a
				href="/species"
				class="drawer-link"
				aria-current={$page.url.pathname.startsWith('/species') ? 'page' : undefined}
				onclick={closeMenu}
			>
				Species
			</a>
			{#if $auth.authenticated}
				<a
					href="/admin"
					class="drawer-link drawer-link-admin"
					aria-current={$page.url.pathname.startsWith('/admin') ? 'page' : undefined}
					onclick={closeMenu}
				>
					Admin
				</a>
			{:else if $auth.checked}
				<a
					href="/login"
					class="drawer-link"
					aria-current={$page.url.pathname === '/login' ? 'page' : undefined}
					onclick={closeMenu}
				>
					Login
				</a>
			{/if}
		</nav>
	{/if}

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
		position: relative;
		z-index: 101;
	}

	.brand {
		color: var(--color-accent);
		font-weight: 600;
		font-size: 1.125rem;
		letter-spacing: -0.025em;
		text-decoration: none;
		white-space: nowrap;
	}

	.divider {
		color: var(--color-border-strong);
	}

	/* ── Full nav (large screens) ── */
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
		white-space: nowrap;
	}
	.nav-link:hover {
		color: var(--color-text);
	}
	.nav-link[aria-current="page"] {
		color: var(--color-text);
		background: var(--color-surface-2);
	}
	.nav-link-admin {
		color: var(--color-accent);
	}
	.nav-link-login {
		opacity: 0.6;
	}

	/* Live link: small pulsing dot */
	.nav-link-live,
	.drawer-link-live {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.nav-live-dot {
		width: 0.375rem;
		height: 0.375rem;
		border-radius: 9999px;
		background: #34d399;
		flex-shrink: 0;
		animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}

	/* ── Header right side ── */
	.header-end {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 0.25rem;
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

	/* ── Hamburger button — hidden on large screens ── */
	.menu-btn {
		display: none;
		padding: 0.375rem;
		border-radius: 0.375rem;
		border: none;
		background: transparent;
		cursor: pointer;
		color: var(--color-text-muted);
		transition: color 0.15s, background-color 0.15s;
		align-items: center;
		justify-content: center;
	}
	.menu-btn:hover {
		color: var(--color-text);
		background: var(--color-surface-2);
	}
	.menu-icon {
		width: 1.25rem;
		height: 1.25rem;
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
	}

	/* ── Dropdown drawer ── */
	.nav-backdrop {
		position: fixed;
		inset: 0;
		top: var(--header-height);
		z-index: 99;
	}
	.nav-drawer {
		position: fixed;
		top: var(--header-height);
		left: 0;
		right: 0;
		z-index: 100;
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border);
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
		display: flex;
		flex-direction: column;
		padding: 0.375rem 0.625rem 0.625rem;
	}
	.drawer-link {
		padding: 0.625rem 0.75rem;
		border-radius: 0.375rem;
		font-size: 0.9375rem;
		text-decoration: none;
		color: var(--color-text-muted);
		transition: color 0.15s, background-color 0.15s;
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.drawer-link:hover {
		color: var(--color-text);
		background: var(--color-surface-2);
	}
	.drawer-link[aria-current="page"] {
		color: var(--color-text);
		background: var(--color-surface-2);
	}
	.drawer-link-admin {
		color: var(--color-accent);
	}

	/* ── Responsive: switch to hamburger below 680px ── */
	@media (max-width: 680px) {
		.nav,
		.divider {
			display: none;
		}
		.menu-btn {
			display: flex;
		}
	}

	/* Dashboard is unusable on narrow screens (redirect kicks in at 900px) */
	@media (max-width: 900px) {
		.dashboard-link {
			display: none;
		}
	}

	/* Takes up remaining vertical space below the header */
	.main {
		flex: 1;
		min-height: 0;
	}
</style>
