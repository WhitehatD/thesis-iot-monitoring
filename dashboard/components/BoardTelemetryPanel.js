"use client";

import { useEffect, useState } from "react";

/**
 * BoardTelemetryPanel — Always-visible panel showing persistent board
 * identity and real-time telemetry extracted from MQTT status messages.
 *
 * Renders firmware version, uptime, last-seen time, and last capture
 * performance metrics.
 */
export default function BoardTelemetryPanel({ boardTelemetry, isBoardOnline }) {
	const [now, setNow] = useState(Date.now());
	const [deployHistory, setDeployHistory] = useState([]);
	const [historyLoading, setHistoryLoading] = useState(true);

	// Fetch deploy history from server
	useEffect(() => {
		let isMounted = true;
		async function fetchHistory() {
			try {
				const res = await fetch("/api/firmware/history");
				if (res.ok && isMounted) {
					const data = await res.json();
					// Sort newest first
					setDeployHistory(
						(data.history || []).sort(
							(a, b) => new Date(b.timestamp) - new Date(a.timestamp),
						),
					);
				}
			} catch (err) {
				console.error("Failed to fetch deploy history:", err);
			} finally {
				if (isMounted) setHistoryLoading(false);
			}
		}
		// Refresh when firmware version changes (e.g., after an OTA update completes)
		fetchHistory();
		return () => {
			isMounted = false;
		};
	}, [boardTelemetry.firmware]);

	// Tick every second for live uptime / last-seen display
	useEffect(() => {
		const interval = setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(interval);
	}, []);

	const { firmware, lastSeen, captureStats, uptimeStart } = boardTelemetry;

	// Don't render if we've never heard from the board
	if (!firmware && !lastSeen) return null;

	const formatUptime = (startMs) => {
		if (!startMs) return "—";
		const seconds = Math.floor((now - startMs) / 1000);
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		const secs = seconds % 60;
		if (minutes < 60) return `${minutes}m ${secs}s`;
		const hours = Math.floor(minutes / 60);
		return `${hours}h ${minutes % 60}m`;
	};

	const formatLastSeen = (ts) => {
		if (!ts) return "—";
		const delta = Math.floor((now - ts) / 1000);
		if (delta < 5) return "just now";
		if (delta < 60) return `${delta}s ago`;
		return `${Math.floor(delta / 60)}m ago`;
	};

	const formatBytes = (bytes) => {
		if (!bytes) return "—";
		if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / 1024).toFixed(0)} KB`;
	};

	const formatLatency = (ms) => {
		if (ms == null) return "—";
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
	};

	const triggerLabels = {
		mqtt_capture_now: "Remote",
		button: "Button",
		scheduled: "Schedule",
	};

	const formatDeployTime = (isoString) => {
		const dt = new Date(isoString);
		return dt.toLocaleDateString(undefined, {
			month: "short",
			day: "numeric",
			hour: "2-digit",
			minute: "2-digit",
		});
	};

	return (
		<div className="board-telemetry-panel">
			<div className="telemetry-header">
				<span className="telemetry-title">
					<span
						className={`telemetry-pulse ${isBoardOnline ? "online" : "offline"}`}
					/>
					Board Telemetry
				</span>
				{firmware && <span className="firmware-badge">v{firmware}</span>}
			</div>

			<div className="telemetry-grid">
				{/* Left — Board Identity */}
				<div className="telemetry-item">
					<span className="telemetry-label">Board</span>
					<span className="telemetry-value">B-U585I-IOT02A</span>
				</div>
				<div className="telemetry-item">
					<span className="telemetry-label">Uptime</span>
					<span className="telemetry-value">{formatUptime(uptimeStart)}</span>
				</div>
				<div className="telemetry-item">
					<span className="telemetry-label">Last Seen</span>
					<span
						className={`telemetry-value ${isBoardOnline ? "value-online" : "value-stale"}`}
					>
						{formatLastSeen(lastSeen)}
					</span>
				</div>

				{/* Right — Capture Performance */}
				<div className="telemetry-item">
					<span className="telemetry-label">Captures</span>
					<span className="telemetry-value">{captureStats.count || "—"}</span>
				</div>
				<div className="telemetry-item">
					<span className="telemetry-label">Last Latency</span>
					<span className="telemetry-value">
						{formatLatency(captureStats.lastLatencyMs)}
					</span>
				</div>
				<div className="telemetry-item">
					<span className="telemetry-label">Frame Size</span>
					<span className="telemetry-value">
						{formatBytes(captureStats.lastSizeBytes)}
					</span>
				</div>
			</div>

			{/* Bottom — Deploy History Timeline */}
			{deployHistory.length > 0 && (
				<div className="telemetry-history-section">
					<div className="telemetry-history-title">Deploy History (CI/CD)</div>
					<div className="telemetry-history-list">
						{deployHistory.slice(0, 5).map((entry, idx) => (
							<div key={idx} className="history-row">
								<div className="history-badge">
									{entry.type === "firmware_upload" ? "Upload" : "Trigger"}
								</div>
								<div className="history-detail">
									{entry.type === "firmware_upload" ? (
										<span>v{entry.version}</span>
									) : (
										<span>
											Commit {entry.commit?.substring(0, 7) || "unknown"}
										</span>
									)}
								</div>
								<div className="history-time">
									{formatDeployTime(entry.timestamp)}
								</div>
							</div>
						))}
					</div>
				</div>
			)}
		</div>
	);
}
