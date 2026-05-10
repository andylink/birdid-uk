<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { initTimezone } from '$lib/timezone';

	let { children } = $props();

	onMount(() => {
		initTimezone();
	});
</script>

<div class="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
	<header class="bg-slate-900 border-b border-slate-800 px-4 py-3 flex items-center gap-4 shrink-0">
		<a href="/" class="flex items-center gap-2 text-emerald-400 font-semibold text-lg tracking-tight">
			<svg viewBox="0 0 24 24" class="w-6 h-6 fill-current" aria-hidden="true">
				<path d="M23 7c0 0-3 .5-4.5 1.5C17.1 5.1 14 3 10.5 3 5.8 3 2 6.8 2 11.5S5.8 20 10.5 20c2.5 0 4.8-1.1 6.4-2.8C18.5 18.5 23 17 23 17V7z"/>
			</svg>
			bird detector
		</a>

		<span class="text-slate-700">|</span>

		<nav class="flex items-center gap-1 text-sm">
			<a
				href="/"
				class="px-2.5 py-1 rounded transition-colors {$page.url.pathname === '/'
					? 'text-slate-100 bg-slate-800'
					: 'text-slate-400 hover:text-slate-200'}"
			>
				Dashboard
			</a>
		<a
			href="/analytics"
			class="px-2.5 py-1 rounded transition-colors {$page.url.pathname.startsWith('/analytics')
				? 'text-slate-100 bg-slate-800'
				: 'text-slate-400 hover:text-slate-200'}"
		>
			Analytics
		</a>
		<a
			href="/species"
			class="px-2.5 py-1 rounded transition-colors {$page.url.pathname.startsWith('/species')
				? 'text-slate-100 bg-slate-800'
				: 'text-slate-400 hover:text-slate-200'}"
		>
			Species
		</a>
	</nav>

		<span class="text-slate-600 text-sm ml-auto">Norfolk garden</span>
	</header>

	<main class="flex-1 min-h-0">
		{@render children()}
	</main>
</div>
