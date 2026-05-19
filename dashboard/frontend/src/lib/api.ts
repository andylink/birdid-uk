/**
 * Typed wrappers around the dashboard API.
 * All functions throw if the server returns a non-2xx response.
 */

const BASE = ''; // empty = same origin; Vite proxies /api/* to the backend

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
	const { headers: extraHeaders, ...rest } = init ?? {};
	const res = await fetch(`${BASE}${path}`, {
		headers: { 'Content-Type': 'application/json', ...extraHeaders },
		...rest
	});
	if (!res.ok) {
		const detail = await res.json().catch(() => ({}));
		throw new Error((detail as { detail?: string })?.detail ?? `HTTP ${res.status}`);
	}
	return res.json() as Promise<T>;
}

// ── Period types ───────────────────────────────────────────────────────────

export type Period = 'today' | '7d' | '30d' | '90d' | 'all';
export type SpeciesPeriod = Period | '365d' | 'custom';

// Labels shown in period-selector dropdowns
export const PERIODS: { value: Period; label: string }[] = [
	{ value: 'today', label: 'Today' },
	{ value: '7d',    label: 'Last 7' },
	{ value: '30d',   label: 'Last 30' },
	{ value: '90d',   label: 'Last 90' },
	{ value: 'all',   label: 'All time' },
];

// Extended period list used on the species page (adds 365d and custom range)
export const SPECIES_PERIODS: { value: SpeciesPeriod; label: string }[] = [
	{ value: 'today',  label: 'Today' },
	{ value: '7d',     label: 'Last 7 days' },
	{ value: '30d',    label: 'Last 30 days' },
	{ value: '90d',    label: 'Last 90 days' },
	{ value: '365d',   label: 'Last 12 months' },
	{ value: 'all',    label: 'All time' },
	{ value: 'custom', label: 'Custom range' },
];

// ── Sort types ─────────────────────────────────────────────────────────────

export type SortOption =
	| 'detections_desc'     | 'detections_asc'
	| 'avg_confidence_desc' | 'avg_confidence_asc'
	| 'peak_confidence_desc'| 'peak_confidence_asc'
	| 'first_detected_asc'  | 'first_detected_desc'
	| 'last_detected_desc'  | 'last_detected_asc'
	| 'name_asc'            | 'name_desc'
	| 'group_asc'           | 'group_desc'
	| 'status_asc'          | 'status_desc'
	| 'bocc_asc'            | 'bocc_desc';

export const SORT_OPTIONS: { value: SortOption; label: string }[] = [
	{ value: 'detections_desc',      label: 'Most detections' },
	{ value: 'detections_asc',       label: 'Least detections' },
	{ value: 'avg_confidence_desc',  label: 'Highest avg confidence' },
	{ value: 'avg_confidence_asc',   label: 'Lowest avg confidence' },
	{ value: 'peak_confidence_desc', label: 'Highest peak confidence' },
	{ value: 'peak_confidence_asc',  label: 'Lowest peak confidence' },
	{ value: 'first_detected_asc',   label: 'First detected (oldest)' },
	{ value: 'first_detected_desc',  label: 'First detected (newest)' },
	{ value: 'last_detected_desc',   label: 'Last detected (recent)' },
	{ value: 'last_detected_asc',    label: 'Last detected (oldest)' },
	{ value: 'name_asc',             label: 'Name A → Z' },
	{ value: 'name_desc',            label: 'Name Z → A' },
	{ value: 'group_asc',            label: 'Group A → Z' },
	{ value: 'group_desc',           label: 'Group Z → A' },
	{ value: 'status_asc',           label: 'Status (Common first)' },
	{ value: 'status_desc',          label: 'Status (Rare first)' },
	{ value: 'bocc_asc',             label: 'BoCC (Green first)' },
	{ value: 'bocc_desc',            label: 'BoCC (Red first)' },
];

// ── Detection types ────────────────────────────────────────────────────────

export interface Detection extends SpeciesInfo {
	id: number;
	timestamp: string;           // ISO 8601
	species: string;
	bto_name: string | null;
	confidence: number;          // 0–1; averaged with CV score when models agree
	filename: string | null;     // audio clip basename; null if no clip was saved
	// ── Inference model ─────────────────────────────────────────────────────
	model: string | null;        // "birdnet" | "perch" | null (legacy rows)
	// ── Cross-validation fields (populated when CV is enabled) ──────────────
	primary_confidence: number | null;  // raw score from the primary model
	cross_validated: number | null;     // 1 if CV ran, 0/null otherwise
	cv_secondary_model: string | null;  // which secondary model ran CV
	cv_species: string | null;          // species identified by the secondary model
	cv_bto_name: string | null;         // BTO name from the secondary model
	cv_confidence: number | null;       // secondary model's confidence score
	cv_agree: number | null;            // 1 = both models agreed, 0 = disagreed
	flagged: number | null;             // 1 = models disagreed but detection was kept (legacy; use verification_status)
	verification_status: string;        // 'unverified' | 'auto' | 'cv' | 'verified'
}

// ── Shared species metadata (from species_info table) ─────────────────────

export interface SpeciesInfo {
	scientific_name:  string | null;
	group_name:       string | null;
	uk_bocc:          string | null;  // "Red" | "Amber" | "Green" | null
	species_status:   string | null;  // "Common" | "Scarce" | "Rare" | "Very rare" | null
	bto_2letter_code: string | null;
	bto_5letter_code: string | null;
}

export interface DailySpeciesSummary extends SpeciesInfo {
	species: string;
	count: number;
	hourly_counts: number[]; // 24 elements, index = hour (0–23)
	first_heard: string | null;   // "HH:MM:SS"
	latest_heard: string | null;  // "HH:MM:SS"
}

export interface HourlyChart {
	labels: string[]; // ["00:00", …, "23:00"]
	data: number[];
}

// ── Analytics types ────────────────────────────────────────────────────────

export interface AnalyticsSummary {
	total_detections: number;
	unique_species: number;
	avg_confidence: number;
	most_common_species: string | null;
	most_common_count: number;
	// Conservation counts (joined from species_info)
	red_list_species: number;
	scarce_rare_species: number;
	groups_represented: number;
	conservation_score: number;
}

export interface TopSpeciesEntry {
	species: string;
	count: number;
	group_name: string | null;
}

export interface NewSpeciesEntry {
	day: string;   // YYYY-MM-DD
	count: number;
}

export interface BoccBreakdownEntry {
	bocc: string;          // "Red" | "Amber" | "Green" | "Unknown"
	species_count: number;
	detection_count: number;
}

export interface GroupBreakdownEntry {
	group_name: string;
	species_count: number;
	detection_count: number;
}

export interface BoccTrendEntry {
	day: string;            // YYYY-MM-DD
	bocc: string;           // "Red" | "Amber" | "Green" | "Unknown"
	detection_count: number;
}

// ── Species types ──────────────────────────────────────────────────────────

export interface SpeciesStats extends SpeciesInfo {
	species: string;
	bto_name: string | null;
	detections: number;
	avg_confidence: number;
	peak_confidence: number;
	first_detected: string;  // ISO 8601
	last_detected: string;   // ISO 8601
}

export interface SpeciesListResponse {
	total: number;
	species: SpeciesStats[];
}

export interface SpeciesDetectionsResponse {
	total: number;
	detections: Detection[];
}

// ── Detections ─────────────────────────────────────────────────────────────

export interface DetectionParams {
	limit?: number;
	offset?: number;
	species?: string;
	date?: string; // YYYY-MM-DD
}

export function getDetections(params: DetectionParams = {}): Promise<Detection[]> {
	const q = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined) q.set(k, String(v));
	}
	return apiFetch<Detection[]>(`/api/v1/detections?${q}`);
}

// ── Analytics ──────────────────────────────────────────────────────────────

export function getDailySpeciesSummary(date: string, limit = 200): Promise<DailySpeciesSummary[]> {
	return apiFetch<DailySpeciesSummary[]>(
		`/api/v1/analytics/species/daily?date=${encodeURIComponent(date)}&limit=${limit}`
	);
}

export function getByHour(date?: string, period?: Period): Promise<HourlyChart> {
	const q = new URLSearchParams();
	if (date)   q.set('date', date);
	if (period) q.set('period', period);
	return apiFetch<HourlyChart>(`/api/v1/analytics/by-hour?${q}`);
}

export function getAnalyticsSummary(period: Period): Promise<AnalyticsSummary> {
	return apiFetch<AnalyticsSummary>(`/api/v1/analytics/summary?period=${period}`);
}

export function getTopSpecies(period: Period, limit = 10): Promise<TopSpeciesEntry[]> {
	return apiFetch<TopSpeciesEntry[]>(
		`/api/v1/analytics/top-species?period=${period}&limit=${limit}`
	);
}

export function getNewSpeciesTimeline(period: Period): Promise<NewSpeciesEntry[]> {
	return apiFetch<NewSpeciesEntry[]>(`/api/v1/analytics/new-species?period=${period}`);
}

// ── Species ────────────────────────────────────────────────────────────────

/** Fetch aggregate stats and metadata for a single species. */
export function getSpeciesDetail(name: string): Promise<SpeciesStats> {
	return apiFetch<SpeciesStats>(`/api/v1/species/${encodeURIComponent(name)}`);
}

/** Fetch a paginated list of individual detections for one species, newest first. */
export function getSpeciesDetections(
	name: string,
	params: { limit?: number; offset?: number; verification_status?: string } = {}
): Promise<SpeciesDetectionsResponse> {
	const q = new URLSearchParams();
	if (params.limit              !== undefined) q.set('limit',               String(params.limit));
	if (params.offset             !== undefined) q.set('offset',              String(params.offset));
	if (params.verification_status !== undefined) q.set('verification_status', params.verification_status);
	return apiFetch<SpeciesDetectionsResponse>(
		`/api/v1/species/${encodeURIComponent(name)}/detections?${q}`
	);
}

export function getSpeciesList(params: {
	period: SpeciesPeriod;
	sort: SortOption;
	date_from?: string;
	date_to?: string;
	limit?: number;
	offset?: number;
	bocc?: string;    // "Red" | "Amber" | "Green"
	status?: string;  // "Common" | "Scarce" | "Rare" | "Very rare"
	group?: string;   // taxonomic group name from species_info
}): Promise<SpeciesListResponse> {
	const q = new URLSearchParams({ period: params.period, sort: params.sort });
	if (params.date_from) q.set('date_from', params.date_from);
	if (params.date_to)   q.set('date_to',   params.date_to);
	if (params.limit)     q.set('limit',      String(params.limit));
	if (params.offset)    q.set('offset',     String(params.offset));
	if (params.bocc)      q.set('bocc',       params.bocc);
	if (params.status)    q.set('status',     params.status);
	if (params.group)     q.set('group',      params.group);
	return apiFetch<SpeciesListResponse>(`/api/v1/species?${q}`);
}

/** Returns the URL for a species thumbnail. The image is served from the backend cache. */
export function speciesImageUrl(species: string): string {
	return `/api/v1/species/image?name=${encodeURIComponent(species)}`;
}

// ── Sun times ──────────────────────────────────────────────────────────────

export interface SunTimes {
	sunrise: string;  // "HH:MM" local time
	sunset:  string;  // "HH:MM" local time
}

/**
 * Fetch sunrise/sunset times for a given local date.
 * Returns null if the endpoint fails (e.g. astral not installed, date out of
 * range) — callers should treat missing sun data as a non-fatal no-op.
 */
export function getSunTimes(date: string): Promise<SunTimes | null> {
	return apiFetch<SunTimes>(`/api/v1/sun?date=${encodeURIComponent(date)}`)
		.catch(() => null);
}

// ── Conservation analytics ─────────────────────────────────────────────────

export function getBoccBreakdown(period: Period): Promise<BoccBreakdownEntry[]> {
	return apiFetch<BoccBreakdownEntry[]>(`/api/v1/analytics/bocc-breakdown?period=${period}`);
}

export function getGroupBreakdown(period: Period, limit = 15): Promise<GroupBreakdownEntry[]> {
	return apiFetch<GroupBreakdownEntry[]>(
		`/api/v1/analytics/group-breakdown?period=${period}&limit=${limit}`
	);
}

export function getBoccTrend(period: Period): Promise<BoccTrendEntry[]> {
	return apiFetch<BoccTrendEntry[]>(`/api/v1/analytics/bocc-trend?period=${period}`);
}

// ── Weather analytics ──────────────────────────────────────────────────────

export interface WeatherStatus {
	total_detections: number;
	with_weather:     number;
	coverage_pct:     number;
}

export interface WeatherSummary {
	avg_temp:              number | null;
	avg_humidity:          number | null;
	avg_wind_speed:        number | null;
	avg_pressure:          number | null;
	most_common_condition: string | null;
}

export interface WeatherConditionEntry {
	condition: string;
	count:     number;
}

export interface WeatherWindSpeedEntry {
	bin:   string;
	label: string;
	count: number;
}

export interface WeatherTempEntry {
	bin:   string;
	label: string;
	count: number;
}

export interface WeatherWindRoseEntry {
	direction: string;
	count:     number;
}

export function getWeatherStatus(period: Period): Promise<WeatherStatus> {
	return apiFetch<WeatherStatus>(`/api/v1/weather/status?period=${period}`);
}

export function getWeatherSummary(period: Period): Promise<WeatherSummary> {
	return apiFetch<WeatherSummary>(`/api/v1/weather/summary?period=${period}`);
}

export function getWeatherByCondition(period: Period): Promise<WeatherConditionEntry[]> {
	return apiFetch<WeatherConditionEntry[]>(`/api/v1/weather/by-condition?period=${period}`);
}

export function getWeatherByWindSpeed(period: Period): Promise<WeatherWindSpeedEntry[]> {
	return apiFetch<WeatherWindSpeedEntry[]>(`/api/v1/weather/by-wind-speed?period=${period}`);
}

export function getWeatherByTemperature(period: Period): Promise<WeatherTempEntry[]> {
	return apiFetch<WeatherTempEntry[]>(`/api/v1/weather/by-temperature?period=${period}`);
}

export function getWeatherWindRose(period: Period): Promise<WeatherWindRoseEntry[]> {
	return apiFetch<WeatherWindRoseEntry[]>(`/api/v1/weather/wind-rose?period=${period}`);
}

// ── Auth ───────────────────────────────────────────────────────────────────

export interface AuthStatus {
	authenticated: boolean;
}

/** Check whether the current session cookie is valid. Never throws. */
export function authMe(): Promise<AuthStatus> {
	return apiFetch<AuthStatus>('/api/v1/auth/me').catch(() => ({ authenticated: false }));
}

/** Submit the admin password; sets the session cookie on success. Throws on failure. */
export function authLogin(password: string): Promise<AuthStatus> {
	return apiFetch<AuthStatus>('/api/v1/auth/login', {
		method: 'POST',
		body: JSON.stringify({ password }),
	});
}

/** Clear the session cookie. */
export function authLogout(): Promise<AuthStatus> {
	return apiFetch<AuthStatus>('/api/v1/auth/logout', { method: 'POST' });
}

// ── Admin types ────────────────────────────────────────────────────────────

export interface AdminCount {
	count: number;
}

export interface AdminDeleteResult {
	deleted_rows: number;
	deleted_files: number;
}

export interface AdminVerificationResult {
	id: number;
	verification_status: string;
}

export interface SystemStatus {
	total_detections: number;
	newest_detection: string | null;
	oldest_detection: string | null;
	disk_total_gb:    number;
	disk_used_gb:     number;
	disk_free_gb:     number;
	disk_used_pct:    number;
}

// ── Admin API functions ────────────────────────────────────────────────────

/** Count detections, optionally filtered by species. */
export function adminCountDetections(species?: string): Promise<AdminCount> {
	const q = species ? `?species=${encodeURIComponent(species)}` : '';
	return apiFetch<AdminCount>(`/api/v1/admin/detections/count${q}`);
}

/** Delete a single detection by ID. */
export function adminDeleteDetection(id: number): Promise<{ id: number; deleted: boolean }> {
	return apiFetch(`/api/v1/admin/detections/${id}`, { method: 'DELETE' });
}

/** Bulk-delete detections, optionally filtered by species. */
export function adminBulkDelete(species?: string): Promise<AdminDeleteResult> {
	const q = species ? `?species=${encodeURIComponent(species)}` : '';
	return apiFetch<AdminDeleteResult>(`/api/v1/admin/detections${q}`, { method: 'DELETE' });
}

/** Return the URL for the CSV export (use as an <a href> download link). */
export function adminExportUrl(species?: string): string {
	const q = species ? `?species=${encodeURIComponent(species)}` : '';
	return `/api/v1/admin/detections/export${q}`;
}

/** Set the verification_status on a detection. Valid values: unverified, auto, cv, verified. */
export function adminSetVerification(id: number, status: string): Promise<AdminVerificationResult> {
	return apiFetch<AdminVerificationResult>(`/api/v1/admin/detections/${id}/verification`, {
		method: 'PATCH',
		body: JSON.stringify({ verification_status: status }),
	});
}

/** Fetch current system status (disk usage, detection counts). */
export function adminSystemStatus(): Promise<SystemStatus> {
	return apiFetch<SystemStatus>('/api/v1/admin/system/status');
}

/** Trigger a retention cleanup run. */
export function adminRunRetention(): Promise<{ clips_deleted: number }> {
	return apiFetch('/api/v1/admin/system/retention', { method: 'POST' });
}

/** Delete all cached species thumbnail images. */
export function adminClearImageCache(): Promise<{ deleted_files: number }> {
	return apiFetch('/api/v1/admin/system/clear-image-cache', { method: 'POST' });
}

/** Wipe and re-seed the species_info table from the JSON filter file. */
export function adminReseedSpecies(): Promise<{ seeded: number }> {
	return apiFetch('/api/v1/admin/system/reseed-species', { method: 'POST' });
}
