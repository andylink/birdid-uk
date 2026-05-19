/**
 * Light/dark theme helpers.
 *
 * The inline script in app.html applies the 'dark' class before first paint
 * to avoid a flash of the wrong theme. This module handles runtime toggling
 * and persisting the user's preference to localStorage.
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
 * Switch to the given theme: updates the <html> class, saves to localStorage,
 * and fires a 'themechange' event for any listeners (e.g. Chart.js components).
 */
export function applyTheme(theme: Theme): void {
	document.documentElement.classList.toggle('dark', theme === 'dark');
	try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) { /* noop */ }
	document.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
}

/** Toggle between light and dark; returns the new theme. */
export function toggleTheme(): Theme {
	const next: Theme = currentTheme() === 'dark' ? 'light' : 'dark';
	applyTheme(next);
	return next;
}
