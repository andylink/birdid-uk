/**
 * Lightweight SSE client with automatic reconnection.
 *
 * Usage:
 *   const sse = createSSE('/stream/detections');
 *   sse.on('detection', (data) => { ... });
 *   onDestroy(() => sse.close());
 */

type SSEHandler = (data: unknown) => void;

export interface SSEClient {
	on(event: string, handler: SSEHandler): void;
	close(): void;
}

export function createSSE(url: string, params?: Record<string, string>): SSEClient {
	const handlers: Map<string, SSEHandler[]> = new Map();
	let es: EventSource | null = null;
	let closed = false;
	let retryDelay = 1000; // ms; doubles on each failed attempt, capped at 30s

	const fullUrl = params
		? `${url}?${new URLSearchParams(params).toString()}`
		: url;

	function connect() {
		if (closed) return;
		es = new EventSource(fullUrl);

		es.addEventListener('detection', (e) => {
			const parsed = JSON.parse((e as MessageEvent).data);
			handlers.get('detection')?.forEach((h) => h(parsed));
		});

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
		},
		close() {
			closed = true;
			es?.close();
		}
	};
}
