"use client";

/**
 * Shows MQTT connection status as a colored badge.
 */
export default function ConnectionStatus({ status }) {
	const labels = {
		connected: "MQTT Connected",
		disconnected: "Disconnected",
		connecting: "Connecting…",
	};

	return (
		<div id="connection-status" className={`connection-badge ${status}`}>
			<span className={`status-dot ${status}`} />
			{labels[status] || "Unknown"}
		</div>
	);
}
