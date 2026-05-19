<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth, logout } from '$lib/auth';
	import {
		adminSystemStatus,
		adminCountDetections,
		adminBulkDelete,
		adminRunRetention,
		adminClearImageCache,
		adminReseedSpecies,
		adminExportUrl,
		type SystemStatus,
	} from '$lib/api';

	// ── State ────────────────────────────────────────────────────────────────

	let status     = $state<SystemStatus | null>(null);
	let statusErr  = $state<string | null>(null);
	let statusLoad = $state(false);

	// Bulk-delete section
	let deleteSpecies = $state('');
	let deleteCount   = $state<number | null>(null);
	let deleteErr     = $state<string | null>(null);
	let deleteLoad    = $state(false);
	let deleteConfirm = $state(false);

	// Tool results
	let toolMsg  = $state<string | null>(null);
	let toolErr  = $state<string | null>(null);
	let toolLoad = $state(false);

	// ── Lifecycle ────────────────────────────────────────────────────────────

	// Track whether we've already kicked off the initial status load so that
	// the $effect below doesn't call loadStatus() more than once if the auth
	// store emits a further update (e.g. the layout re-checks the session).
	let _statusRequested = false;

	$effect(() => {
		if ($auth.checked && !$auth.authenticated) {
			goto('/login');
		}
		if ($auth.checked && $auth.authenticated && !_statusRequested) {
			_statusRequested = true;
			loadStatus();
		}
	});

	// ── Helpers ──────────────────────────────────────────────────────────────

	async function loadStatus() {
		statusLoad = true;
		statusErr  = null;
		try {
			status = await adminSystemStatus();
		} catch (e) {
			statusErr = (e as Error).message;
		} finally {
			statusLoad = false;
		}
	}

	async function lookupDeleteCount() {
		deleteCount = null;
		deleteErr   = null;
		deleteConfirm = false;
		try {
			const r = await adminCountDetections(deleteSpecies || undefined);
			deleteCount = r.count;
		} catch (e) {
			deleteErr = (e as Error).message;
		}
	}

	async function confirmBulkDelete() {
		deleteLoad = true;
		deleteErr  = null;
		try {
			const r = await adminBulkDelete(deleteSpecies || undefined);
			toolMsg  = `Deleted ${r.deleted_rows} detections and ${r.deleted_files} clip files.`;
			deleteCount   = null;
			deleteConfirm = false;
			deleteSpecies = '';
			await loadStatus();
		} catch (e) {
			deleteErr = (e as Error).message;
		} finally {
			deleteLoad = false;
		}
	}

	async function runTool(fn: () => Promise<string>) {
		toolMsg  = null;
		toolErr  = null;
		toolLoad = true;
		try {
			toolMsg = await fn();
		} catch (e) {
			toolErr = (e as Error).message;
		} finally {
			toolLoad = false;
		}
	}

	async function handleLogout() {
		await logout();
		goto('/');
	}
</script>

<svelte:head>
	<title>Admin — Bird Detector</title>
</svelte:head>

<div class="page-scroll">
	<div class="page-inner">

		<!-- Header -->
		<div class="page-header">
			<h1 class="page-title">Admin</h1>
			<button class="logout-btn" onclick={handleLogout}>Log out</button>
		</div>

		{#if !$auth.checked}
			<p class="muted">Checking session…</p>
		{:else if !$auth.authenticated}
			<p class="muted">Not logged in. <a href="/login" class="link">Log in</a></p>
		{:else}

		<!-- ── System status ────────────────────────────────────────────────── -->
		<section class="section">
			<h2 class="section-title">System status</h2>
			{#if statusLoad}
				<p class="muted">Loading…</p>
			{:else if statusErr}
				<p class="error-text">{statusErr}</p>
			{:else if status}
				<div class="stat-grid">
					<div class="stat-cell">
						<span class="stat-label">Total detections</span>
						<span class="stat-value">{status.total_detections.toLocaleString()}</span>
					</div>
					<div class="stat-cell">
						<span class="stat-label">Oldest detection</span>
						<span class="stat-value mono">{status.oldest_detection?.slice(0, 10) ?? '—'}</span>
					</div>
					<div class="stat-cell">
						<span class="stat-label">Newest detection</span>
						<span class="stat-value mono">{status.newest_detection?.slice(0, 10) ?? '—'}</span>
					</div>
					<div class="stat-cell">
						<span class="stat-label">Disk used</span>
						<span class="stat-value">{status.disk_used_gb} GB / {status.disk_total_gb} GB ({status.disk_used_pct}%)</span>
					</div>
					<div class="stat-cell">
						<span class="stat-label">Disk free</span>
						<span class="stat-value">{status.disk_free_gb} GB</span>
					</div>
				</div>
				<button class="text-btn" onclick={loadStatus}>Refresh</button>
			{/if}
		</section>

		<!-- ── Delete detections ────────────────────────────────────────────── -->
		<section class="section">
			<h2 class="section-title">Delete detections</h2>
			<p class="section-desc">
				Delete detections and their audio clips. Leave species blank to target all detections.
			</p>

			<div class="row-group">
				<input
					type="text"
					class="text-input"
					placeholder="Species name (blank = all)"
					bind:value={deleteSpecies}
					oninput={() => { deleteCount = null; deleteConfirm = false; }}
				/>
				<button class="secondary-btn" onclick={lookupDeleteCount}>
					Count
				</button>
				<a
					href={adminExportUrl(deleteSpecies || undefined)}
					download="detections.csv"
					class="secondary-btn"
				>
					Export CSV
				</a>
			</div>

			{#if deleteCount !== null}
				<p class="count-line">
					{deleteCount} detection{deleteCount !== 1 ? 's' : ''}
					{deleteSpecies ? `for "${deleteSpecies}"` : 'total'} will be deleted.
				</p>
				{#if !deleteConfirm}
					<button
						class="danger-btn"
						disabled={deleteCount === 0}
						onclick={() => (deleteConfirm = true)}
					>
						Delete {deleteCount} detection{deleteCount !== 1 ? 's' : ''}
					</button>
				{:else}
					<div class="confirm-row">
						<span class="confirm-label">Are you sure? This cannot be undone.</span>
						<button class="danger-btn" disabled={deleteLoad} onclick={confirmBulkDelete}>
							{deleteLoad ? 'Deleting…' : 'Confirm delete'}
						</button>
						<button class="secondary-btn" onclick={() => (deleteConfirm = false)}>Cancel</button>
					</div>
				{/if}
			{/if}

			{#if deleteErr}
				<p class="error-text">{deleteErr}</p>
			{/if}
		</section>

		<!-- ── System tools ─────────────────────────────────────────────────── -->
		<section class="section">
			<h2 class="section-title">System tools</h2>

			{#if toolMsg}
				<p class="success-msg" role="status">{toolMsg}</p>
			{/if}
			{#if toolErr}
				<p class="error-text" role="alert">{toolErr}</p>
			{/if}

			<div class="tool-grid">
				<div class="tool-card">
					<div class="tool-info">
						<span class="tool-name">Run retention</span>
						<span class="tool-desc">Apply the retention policy and delete old clips now.</span>
					</div>
					<button
						class="secondary-btn"
						disabled={toolLoad}
						onclick={() => runTool(async () => {
							const r = await adminRunRetention();
							return `Retention run complete — ${r.clips_deleted} clip(s) deleted.`;
						})}
					>
						Run
					</button>
				</div>

				<div class="tool-card">
					<div class="tool-info">
						<span class="tool-name">Clear image cache</span>
						<span class="tool-desc">Delete all cached species thumbnails so fresh ones are fetched.</span>
					</div>
					<button
						class="secondary-btn"
						disabled={toolLoad}
						onclick={() => runTool(async () => {
							const r = await adminClearImageCache();
							return `Image cache cleared — ${r.deleted_files} file(s) deleted.`;
						})}
					>
						Clear
					</button>
				</div>

				<div class="tool-card">
					<div class="tool-info">
						<span class="tool-name">Re-seed species info</span>
						<span class="tool-desc">Wipe and re-seed the species_info table from the JSON filter file.</span>
					</div>
					<button
						class="secondary-btn"
						disabled={toolLoad}
						onclick={() => runTool(async () => {
							const r = await adminReseedSpecies();
							return `Species info re-seeded — ${r.seeded} species inserted.`;
						})}
					>
						Re-seed
					</button>
				</div>
			</div>
		</section>

		{/if}
	</div>
</div>

<style>
	.page-scroll {
		height: calc(100vh - var(--header-height));
		overflow-y: auto;
	}

	.page-inner {
		max-width: 52rem;
		margin: 0 auto;
		padding: 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 2rem;
	}

	.page-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.page-title {
		margin: 0;
		font-size: 1.25rem;
		font-weight: 700;
		color: var(--color-text);
	}

	.logout-btn {
		padding: 0.375rem 0.75rem;
		border-radius: 0.375rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		color: var(--color-text-muted);
		font-size: 0.8125rem;
		cursor: pointer;
		transition: color 0.15s;
	}
	.logout-btn:hover { color: var(--color-text); }

	/* Sections */
	.section {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.875rem;
	}

	.section-title {
		margin: 0;
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-text-muted);
	}

	.section-desc {
		margin: -0.375rem 0 0;
		font-size: 0.8125rem;
		color: var(--color-text-muted);
	}

	/* Stat grid */
	.stat-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 0.625rem;
	}
	@media (min-width: 640px) { .stat-grid { grid-template-columns: repeat(3, 1fr); } }

	.stat-cell {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: 0.375rem;
		padding: 0.625rem 0.75rem;
	}

	.stat-label {
		font-size: 0.625rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-text-dim);
	}

	.stat-value {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text);
	}
	.stat-value.mono {
		font-family: ui-monospace, 'Cascadia Code', monospace;
	}

	/* Form elements */
	.row-group {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.text-input {
		flex: 1;
		min-width: 12rem;
		padding: 0.4375rem 0.75rem;
		border-radius: 0.375rem;
		border: 1px solid var(--color-border-strong);
		background: var(--color-page);
		color: var(--color-text);
		font-size: 0.875rem;
		outline: none;
	}
	.text-input:focus { border-color: var(--color-accent); }

	.count-line {
		margin: 0;
		font-size: 0.875rem;
		color: var(--color-text-muted);
	}

	.confirm-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.confirm-label {
		font-size: 0.8125rem;
		color: #fbbf24;
	}

	/* Buttons */
	.secondary-btn {
		padding: 0.4375rem 0.875rem;
		border-radius: 0.375rem;
		border: 1px solid var(--color-border-strong);
		background: transparent;
		color: var(--color-text-muted);
		font-size: 0.8125rem;
		cursor: pointer;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		transition: color 0.15s, background-color 0.15s;
		white-space: nowrap;
	}
	.secondary-btn:hover:not(:disabled) {
		color: var(--color-text);
		background: var(--color-surface-2);
	}
	.secondary-btn:disabled { opacity: 0.4; cursor: not-allowed; }

	.danger-btn {
		padding: 0.4375rem 0.875rem;
		border-radius: 0.375rem;
		border: none;
		background: #ef4444;
		color: #fff;
		font-size: 0.8125rem;
		font-weight: 600;
		cursor: pointer;
		transition: opacity 0.15s;
		white-space: nowrap;
	}
	.danger-btn:hover:not(:disabled) { opacity: 0.85; }
	.danger-btn:disabled { opacity: 0.4; cursor: not-allowed; }

	.text-btn {
		padding: 0.25rem 0;
		border: none;
		background: transparent;
		color: var(--color-text-muted);
		font-size: 0.75rem;
		cursor: pointer;
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.text-btn:hover { color: var(--color-text); }

	/* Tool grid */
	.tool-grid {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.tool-card {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: 0.375rem;
		padding: 0.75rem 1rem;
	}

	.tool-info {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}

	.tool-name {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text);
	}

	.tool-desc {
		font-size: 0.75rem;
		color: var(--color-text-muted);
	}

	/* Feedback */
	.success-msg {
		margin: 0;
		font-size: 0.8125rem;
		color: #34d399;
		background: rgba(52, 211, 153, 0.08);
		border: 1px solid rgba(52, 211, 153, 0.2);
		border-radius: 0.375rem;
		padding: 0.5rem 0.75rem;
	}

	.error-text {
		margin: 0;
		font-size: 0.8125rem;
		color: #f87171;
	}

	.muted {
		color: var(--color-text-muted);
		font-size: 0.875rem;
	}

	.link {
		color: var(--color-accent);
		text-decoration: underline;
	}
</style>
