/**
 * Shared authentication state for the admin interface.
 *
 * Import `auth` to read the current session state reactively.
 * Call `checkAuth()` on mount to initialise it from the server.
 */

import { writable } from 'svelte/store';
import { authMe, authLogin as apiLogin, authLogout as apiLogout } from './api';

export interface AuthState {
	authenticated: boolean;
	checked:       boolean;   // false until the first authMe() call has completed
}

export const auth = writable<AuthState>({ authenticated: false, checked: false });

/** Check the current session cookie against the server and update the store. */
export async function checkAuth(): Promise<void> {
	const result = await authMe();
	auth.set({ authenticated: result.authenticated, checked: true });
}

/** Submit a password; update the store on success. Throws on invalid password. */
export async function login(password: string): Promise<void> {
	const result = await apiLogin(password);
	if (!result.authenticated) {
		throw new Error('Invalid password');
	}
	auth.set({ authenticated: true, checked: true });
}

/** Clear the session cookie and update the store. */
export async function logout(): Promise<void> {
	await apiLogout();
	auth.set({ authenticated: false, checked: true });
}
