<script lang="ts">
	import { goto } from '$app/navigation';
	import { login } from '$lib/auth';

	let password = $state('');
	let error    = $state<string | null>(null);
	let loading  = $state(false);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error   = null;
		loading = true;
		try {
			await login(password);
			goto('/admin');
		} catch (err) {
			error = (err as Error).message ?? 'Login failed';
		} finally {
			loading = false;
		}
	}
</script>

<div class="login-wrap">
	<div class="login-card">
		<h1 class="login-title">Admin login</h1>
		<p class="login-sub">Enter your admin password to continue.</p>

		<form class="login-form" onsubmit={handleSubmit}>
			<label class="field-label" for="password">Password</label>
			<input
				id="password"
				type="password"
				class="field-input"
				class:field-error={!!error}
				bind:value={password}
				autocomplete="current-password"
				disabled={loading}
			/>

			{#if error}
				<p class="error-msg" role="alert">{error}</p>
			{/if}

			<button type="submit" class="submit-btn" disabled={loading || !password}>
				{loading ? 'Logging in…' : 'Log in'}
			</button>
		</form>
	</div>
</div>

<style>
	.login-wrap {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: calc(100vh - var(--header-height));
		padding: 2rem 1rem;
	}

	.login-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		padding: 2rem;
		width: 100%;
		max-width: 22rem;
	}

	.login-title {
		margin: 0 0 0.25rem;
		font-size: 1.25rem;
		font-weight: 700;
		color: var(--color-text);
	}

	.login-sub {
		margin: 0 0 1.5rem;
		font-size: 0.875rem;
		color: var(--color-text-muted);
	}

	.login-form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.field-label {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--color-text-muted);
		margin-bottom: -0.25rem;
	}

	.field-input {
		width: 100%;
		padding: 0.5rem 0.75rem;
		border-radius: 0.375rem;
		border: 1px solid var(--color-border-strong);
		background: var(--color-page);
		color: var(--color-text);
		font-size: 0.875rem;
		outline: none;
		box-sizing: border-box;
		transition: border-color 0.15s;
	}
	.field-input:focus {
		border-color: var(--color-accent);
	}
	.field-input.field-error {
		border-color: #ef4444;
	}

	.error-msg {
		margin: 0;
		font-size: 0.8125rem;
		color: #ef4444;
	}

	.submit-btn {
		padding: 0.5rem 1rem;
		border-radius: 0.375rem;
		border: none;
		background: var(--color-accent);
		color: #fff;
		font-size: 0.875rem;
		font-weight: 600;
		cursor: pointer;
		transition: opacity 0.15s;
		margin-top: 0.25rem;
	}
	.submit-btn:hover:not(:disabled) {
		opacity: 0.85;
	}
	.submit-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
</style>
