const BACKEND = process.env.BACKEND_URL || "http://server:8000";

export async function GET(
	_request: Request,
	{ params }: { params: Promise<{ id: string }> },
) {
	const { id } = await params;
	const res = await fetch(`${BACKEND}/api/agent/sessions/${id}/messages`);
	return new Response(await res.text(), {
		status: res.status,
		headers: { "Content-Type": "application/json" },
	});
}

export async function DELETE(
	_request: Request,
	{ params }: { params: Promise<{ id: string }> },
) {
	const { id } = await params;
	const res = await fetch(`${BACKEND}/api/agent/sessions/${id}/messages`, {
		method: "DELETE",
	});
	return new Response(await res.text(), {
		status: res.status,
		headers: { "Content-Type": "application/json" },
	});
}
