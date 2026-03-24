"use client";

import { useState } from "react";

/**
 * Trigger an immediate camera capture via the FastAPI server.
 */
export default function CaptureButton({ onCaptureStart }) {
	const [loading, setLoading] = useState(false);

	const apiBase =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_API_URL ||
				`http://${window.location.hostname}:8000`
			: "http://localhost:8000";

	const handleCapture = async () => {
		if (onCaptureStart) onCaptureStart();
		setLoading(true);
		try {
			const res = await fetch(`${apiBase}/api/capture`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ objective: "Visual inspection" }),
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
		} catch (err) {
			console.error("Capture failed:", err);
		} finally {
			setLoading(false);
		}
	};

	return (
		<button
			id="capture-button"
			className="capture-btn"
			onClick={handleCapture}
			disabled={loading}
		>
			{loading ? (
				<>
					<span className="spinner" />
					Sending…
				</>
			) : (
				<>
					<span className="icon">📷</span>
					Capture Now
				</>
			)}
		</button>
	);
}
