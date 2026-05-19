<script lang="ts">
	interface Props {
		title: string;
		value: string | number | null | undefined;
		subtitle?: string;
		loading?: boolean;
	}

	let { title, value, subtitle, loading = false }: Props = $props();
</script>

<div class="stat-card">
	<div class="stat-title">{title}</div>

	{#if loading}
		<!-- Skeleton placeholders match the size of the real value and subtitle -->
		<div class="skeleton-value skeleton-pulse"></div>
		<div class="skeleton-sub skeleton-pulse"></div>
	{:else}
		<div class="stat-value">{value ?? '—'}</div>
		{#if subtitle}
			<div class="stat-subtitle">{subtitle}</div>
		{/if}
	{/if}
</div>

<style>
	.stat-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		padding: 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.stat-title {
		font-size: 0.625rem;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	.stat-value {
		font-size: 1.5rem;
		font-weight: 700;
		color: var(--color-text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.stat-subtitle {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}

	.skeleton-value {
		height: 2rem;
		margin-top: 0.25rem;
		background: var(--color-skeleton);
		border-radius: 0.25rem;
		width: 66%;
	}
	.skeleton-sub {
		height: 0.75rem;
		margin-top: 0.25rem;
		background: var(--color-skeleton);
		border-radius: 0.25rem;
		width: 40%;
	}
</style>
