/**
 * SSE Proxy Route — streams agent chat from FastAPI without buffering.
 *
 * Next.js rewrites() buffers entire responses, killing SSE streaming.
 * This App Router handler fetches from FastAPI and pipes the ReadableStream
 * directly to the browser, preserving real-time event delivery.
 */

const BACKEND_URL = process.env.BACKEND_URL || "http://server:8000";

export async function POST(request: Request) {
	const body = await request.json();

	const upstream = await fetch(`${BACKEND_URL}/api/agent/chat`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});

	if (!upstream.ok || !upstream.body) {
		return new Response(
			JSON.stringify({ error: `Backend error: ${upstream.status}` }),
			{
				status: upstream.status,
				headers: { "Content-Type": "application/json" },
			},
		);
	}

	return new Response(upstream.body, {
		status: 200,
		headers: {
			"Content-Type": "text/event-stream",
			"Cache-Control": "no-cache, no-transform",
			Connection: "keep-alive",
			"X-Accel-Buffering": "no",
		},
	});
}
