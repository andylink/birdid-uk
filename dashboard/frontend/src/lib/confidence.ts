/** Confidence thresholds — must stay in sync with dashboard/config.py */
export const CONF_HIGH = 0.9;
export const CONF_MED = 0.7;

export type ConfidenceLevel = 'high' | 'medium' | 'low';

export function confidenceLevel(score: number): ConfidenceLevel {
	if (score >= CONF_HIGH) return 'high';
	if (score >= CONF_MED) return 'medium';
	return 'low';
}

export function confidenceBadgeClass(score: number): string {
	const level = confidenceLevel(score);
	return {
		high: 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/40',
		medium: 'bg-amber-500/20 text-amber-400 ring-1 ring-amber-500/40',
		low: 'bg-slate-500/20 text-slate-400 ring-1 ring-slate-500/40'
	}[level];
}

export function formatConfidence(score: number): string {
	return `${Math.round(score * 100)}%`;
}
