<script lang="ts">
	interface Props {
		title: string;
		value: string | number | null | undefined;
		subtitle?: string;
		loading?: boolean;
	}

	let { title, value, subtitle, loading = false }: Props = $props();
</script>

<div class="bg-slate-900 border border-slate-800 rounded-lg p-4 flex flex-col gap-1">
	<div class="text-xs font-semibold text-slate-400 uppercase tracking-widest">{title}</div>

	{#if loading}
		<div class="h-8 mt-1 bg-slate-800 rounded animate-pulse w-2/3"></div>
		<div class="h-3 mt-1 bg-slate-800 rounded animate-pulse w-1/3"></div>
	{:else}
		<div class="text-2xl font-bold text-slate-100 truncate">{value ?? '—'}</div>
		{#if subtitle}
			<div class="text-xs text-slate-500">{subtitle}</div>
		{/if}
	{/if}
</div>
