"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useBoardTracker } from "./hooks/useMQTT";

const FLEET_TOPICS = ["device/+/status"];

export default function DashboardPage() {
	const { boards, connectionStatus } = useBoardTracker(FLEET_TOPICS);
	const [now, setNow] = useState(Date.now());

	// Tick every second so "Last Seen" stays fresh
	useEffect(() => {
		const timer = setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(timer);
	}, []);

	const boardList = Object.values(boards);

	return (
		<div className="app-container">
			<header className="header">
				<div className="header-title-container">
					<div className="header-logo">
						<svg
							width="22"
							height="22"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
							strokeLinejoin="round"
							style={{ color: "var(--accent)" }}
							aria-hidden="true"
						>
							<circle cx="12" cy="12" r="3" />
							<path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
						</svg>
					</div>
					<div>
						<h1 className="header-title">Visual Monitor</h1>
						<div className="header-subtitle">IoT Edge Fleet Dashboard</div>
					</div>
				</div>
				<div className="connection-badge">
					<div
						className={`connection-dot ${connectionStatus === "connected" ? "connected" : "disconnected"}`}
					/>
					{connectionStatus === "connected" ? "MQTT Connected" : "Disconnected"}
				</div>
			</header>

			<section>
				<div className="boards-grid">
					{boardList.length === 0 && connectionStatus === "connected" && (
						<div className="empty-state" style={{ gridColumn: "1 / -1" }}>
							Waiting for edge nodes to check in via MQTT...
						</div>
					)}

					{boardList.length === 0 && connectionStatus !== "connected" && (
						<div className="loading-card" style={{ gridColumn: "1 / -1" }}>
							<div className="skeleton skeleton-line" />
							<div className="skeleton skeleton-line" />
							<div className="skeleton skeleton-line" />
						</div>
					)}

					{boardList.map((board) => {
						const seenAgo = board.lastSeen
							? Math.floor((now - board.lastSeen) / 1000)
							: null;
						return (
							<div key={board.id} className="board-card">
								<div className="board-header">
									<div className="board-name-group">
										<div className="board-icon">
											<svg
												width="18"
												height="18"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												aria-hidden="true"
												strokeWidth="2"
												strokeLinecap="round"
												strokeLinejoin="round"
												style={{ color: "var(--accent)" }}
											>
												<rect x="4" y="4" width="16" height="16" rx="2" />
												<rect x="9" y="9" width="6" height="6" />
												<path d="M15 2v2M15 20v2M2 15h2M20 15h2M9 2v2M9 20v2M2 9h2M20 9h2" />
											</svg>
										</div>
										<div>
											<div className="board-name">{board.name}</div>
											<div className="board-id">{board.id}</div>
										</div>
									</div>
									<div
										className={`status-indicator ${board.isOnline ? "online" : "offline"}`}
									>
										<div className="dot" />
										{board.isOnline ? "Online" : "Offline"}
									</div>
								</div>

								<div className="stats-grid">
									<div className="stat-item">
										<span className="stat-label">Firmware</span>
										<span className="stat-value">
											{board.firmware ? `v${board.firmware}` : "\u2014"}
										</span>
									</div>
									<div className="stat-item">
										<span className="stat-label">Captures</span>
										<span className="stat-value highlight">
											{board.captures}
										</span>
									</div>
								</div>

								<div className="telemetry-box">
									<div className="telemetry-row">
										<span>State</span>
										<span
											className={`telemetry-val ${getStatusClass(board.status)}`}
										>
											{board.status}
										</span>
									</div>
									<div className="telemetry-row">
										<span>Latency</span>
										<span className="telemetry-val">
											{board.lastLatencyMs
												? `${board.lastLatencyMs}ms`
												: "\u2014"}
										</span>
									</div>
									<div className="telemetry-row">
										<span>Payload</span>
										<span className="telemetry-val">
											{board.lastImageSize
												? `${(board.lastImageSize / 1024).toFixed(1)} KB`
												: "\u2014"}
										</span>
									</div>
									<div className="telemetry-row">
										<span>Last Seen</span>
										<span className="telemetry-val">
											{seenAgo !== null ? `${seenAgo}s ago` : "Never"}
										</span>
									</div>
								</div>

								<div className="board-actions">
									<Link
										href={`/board/${board.id}`}
										className="btn btn-primary btn-explore"
									>
										Open Dashboard <span className="arrow">&rarr;</span>
									</Link>
								</div>
							</div>
						);
					})}
				</div>
			</section>
		</div>
	);
}

function getStatusClass(status: string): string {
	if (status.includes("error") || status.includes("failed"))
		return "status-error";
	if (status.includes("captur") || status.includes("upload"))
		return "status-active";
	if (status.includes("ota") || status.includes("ping")) return "status-ota";
	return "status-idle";
}
