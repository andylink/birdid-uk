/**
 * Lightweight SSE client with automatic reconnection.
 *
 * Usage:
 *   const sse = createSSE('/stream/detections');
 *   sse.on('detection', (data) => { ... });
 *   onDestroy(() => sse.close());
 *
 * Any number of event types can be registered via on().  Each type is wired
 * to the underlying EventSource immediately and re-wired after every reconnect.
 * The special 'open' event fires with null data when the connection is established.
 */

type SSEHandler = (data: unknown) => void;

export interface SSEClient {
	on(event: string, handler: SSEHandler): void;
	close(): void;
}

export function createSSE(url: string, params?: Record<string, string>): SSEClient {
	const handlers: Map<string, SSEHandler[]> = new Map();
	// Tracks which event types have been wired to the current EventSource instance.
	// Reset on every reconnect so we don't skip re-wiring after a new es is created.
	const wiredEvents: Set<string> = new Set();
	let es: EventSource | null = null;
	let closed = false;
	let retryDelay = 1000; // ms; doubles on each failed attempt, capped at 30s

	const fullUrl = params
		? `${url}?${new URLSearchParams(params).toString()}`
		: url;

	/**
	 * Attach a single fan-out listener for `event` to the current EventSource.
	 * No-ops if already wired, not yet connected, or the event is 'open'
	 * (which is dispatched via es.onopen instead).
	 */
	function wireEvent(event: string): void {
		if (!es || wiredEvents.has(event) || event === 'open') return;
		es.addEventListener(event, (e) => {
			const parsed = JSON.parse((e as MessageEvent).data);
			handlers.get(event)?.forEach((h) => h(parsed));
		});
		wiredEvents.add(event);
	}

	function connect() {
		if (closed) return;
		wiredEvents.clear();
		es = new EventSource(fullUrl);

		// Replay all registered event types onto the fresh EventSource so
		// detections are never missed after a reconnect.
		for (const event of handlers.keys()) {
			wireEvent(event);
		}

		es.onerror = () => {
			es?.close();
			if (!closed) {
				// Exponential back-off so a flaky connection doesn't hammer the server
				setTimeout(connect, retryDelay);
				retryDelay = Math.min(retryDelay * 2, 30_000);
			}
		};

		es.onopen = () => {
			retryDelay = 1000; // reset back-off after a successful connection
			handlers.get('open')?.forEach((h) => h(null));
		};
	}

	connect();

	return {
		on(event: string, handler: SSEHandler) {
			if (!handlers.has(event)) handlers.set(event, []);
			handlers.get(event)!.push(handler);
			// Wire this event type to the live EventSource if it hasn't been yet.
			// Handles the common case where on() is called after createSSE().
			wireEvent(event);
		},
		close() {
			closed = true;
			es?.close();
		}
	};
}
