// Thresholds must stay in sync with dashboard/config.py
export const CONF_HIGH = 0.9;
export const CONF_MED = 0.7;

export type ConfidenceLevel = 'high' | 'medium' | 'low';

export function confidenceLevel(score: number): ConfidenceLevel {
	if (score >= CONF_HIGH) return 'high';
	if (score >= CONF_MED) return 'medium';
	return 'low';
}

/** Returns a CSS class for styling a confidence badge (defined in app.css). */
export function confidenceBadgeClass(score: number): string {
	const level = confidenceLevel(score);
	return {
		high:   'conf-badge-high',
		medium: 'conf-badge-medium',
		low:    'conf-badge-low',
	}[level];
}

export function formatConfidence(score: number): string {
	return `${Math.round(score * 100)}%`;
}
