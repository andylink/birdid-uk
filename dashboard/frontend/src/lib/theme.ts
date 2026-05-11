/**
 * theme.ts — light/dark mode helpers.
 *
 * The inline script in app.html applies the 'dark' class before first paint.
 * This module provides runtime toggle + localStorage persistence.
 *
 * Chart components listen for the 'themechange' CustomEvent on document
 * to update their hardcoded colours when the theme switches.
 */

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

/** Read the current theme from the <html> class list. */
export function currentTheme(): Theme {
	return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

/**
 * Apply a theme: toggle the 'dark' class, persist to localStorage,
 * and dispatch a 'themechange' event so Chart.js components can update.
 */
export function applyTheme(theme: Theme): void {
	document.documentElement.classList.toggle('dark', theme === 'dark');
	try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) { /* noop */ }
	document.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
}

/** Toggle between light and dark, return the new theme. */
export function toggleTheme(): Theme {
	const next: Theme = currentTheme() === 'dark' ? 'light' : 'dark';
	applyTheme(next);
	return next;
}
