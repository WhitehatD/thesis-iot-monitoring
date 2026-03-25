"use client";

import mqtt from "mqtt";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

interface BoardTelemetry {
	id: string;
	name: string;
	firmware: string | null;
	lastSeen: number | null;
	status: string;
	captures: number;
	lastImageSize: number | null;
	lastLatencyMs: number | null;
	isOnline: boolean;
}

export default function DashboardPage() {
	const [boards, setBoards] = useState<Record<string, BoardTelemetry>>({});
	const [globalStatus, setGlobalStatus] = useState("connecting");
	const mqttClientRef = useRef<mqtt.MqttClient | null>(null);

	const mqttUrl =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_MQTT_WS_URL ||
				`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/mqtt`
			: "ws://localhost:9001";

	useEffect(() => {
		// Setup MQTT
		const client = mqtt.connect(mqttUrl, { reconnectPeriod: 3000 });
		mqttClientRef.current = client;

		client.on("connect", () => {
			setGlobalStatus("connected");
			client.subscribe("device/+/status", { qos: 0 }); // Subscribe to any device
			client.subscribe("device/stm32/status", { qos: 0 }); // Fallback for legacy topic
		});

		client.on("message", (topic, payload) => {
			try {
				const data = JSON.parse(payload.toString());

				// Handle board status
				let boardId = "stm32-iot-cam-01";
				if (topic.startsWith("device/")) {
					const parts = topic.split("/");
					if (parts.length >= 3 && parts[1] !== "stm32") {
						boardId = parts[1];
					}
				}
				if (data.client_id || data.board_id) {
					boardId = data.client_id || data.board_id;
				}

				setBoards((prev) => {
					const curr = prev[boardId] || {
						id: boardId,
						name: `STM32 B-U585I-IOT02A`,
						firmware: null,
						lastSeen: null,
						status: "idle",
						captures: 0,
						lastImageSize: null,
						lastLatencyMs: null,
						isOnline: true,
					};

					const update = { ...curr, isOnline: true, lastSeen: Date.now() };

					if (data.firmware) update.firmware = data.firmware;
					if (data.status) {
						update.status = data.status;
					}
					if (data.status === "captured" || data.status === "uploaded") {
						update.captures += 1;
						if (data.size) update.lastImageSize = data.size;
						if (data.latency_ms) update.lastLatencyMs = data.latency_ms;
					}

					return { ...prev, [boardId]: update };
				});
			} catch (e) {
				console.error("MQTT parse err", e);
			}
		});

		client.on("close", () => setGlobalStatus("disconnected"));
		client.on("error", () => setGlobalStatus("error"));

		// Online checker interval
		const interval = setInterval(() => {
			setBoards((prev) => {
				let changed = false;
				const next = { ...prev };
				const now = Date.now();
				for (const id in next) {
					// If not seen for 15s, mark offline
					if (
						next[id].isOnline &&
						next[id].lastSeen &&
						now - next[id].lastSeen! > 15000
					) {
						next[id] = { ...next[id], isOnline: false };
						changed = true;
					}
				}
				return changed ? next : prev;
			});
		}, 5000);

		return () => {
			client.end();
			clearInterval(interval);
		};
	}, [mqttUrl]);

	const getStatusClass = (status: string) => {
		if (status.includes("error") || status.includes("failed"))
			return "status-error";
		if (status.includes("captur") || status.includes("upload"))
			return "status-active";
		if (status.includes("ota") || status.includes("ping")) return "status-ota";
		return "status-idle";
	};

	return (
		<div className="app-container">
			<header className="header">
				<div className="header-title-container">
					<div className="header-logo">👁</div>
					<div>
						<h1 className="header-title">Enterprise Visual Edge</h1>
						<div className="header-subtitle">
							Distributed STM32 Multimodal Fleet
						</div>
					</div>
				</div>
				<div className="connection-badge">
					<div
						className={`connection-dot ${globalStatus === "connected" ? "connected" : "disconnected"}`}
					/>
					{globalStatus === "connected"
						? "Broker Connected"
						: "Broker Disconnected"}
				</div>
			</header>

			<section>
				<div className="boards-grid">
					{Object.values(boards).length === 0 ? (
						<div
							className="glass-panel hoverable-card"
							style={{
								gridColumn: "1 / -1",
								textAlign: "center",
								color: "var(--text-tertiary)",
							}}
						>
							Waiting for edge nodes to check in...
						</div>
					) : (
						Object.values(boards).map((board) => (
							<div
								key={board.id}
								className="board-card glass-panel hoverable-card"
							>
								<div className="board-header">
									<div className="board-name-group">
										<div className="board-icon">⚡</div>
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
											{board.firmware ? `v${board.firmware}` : "—"}
										</span>
									</div>
									<div className="stat-item">
										<span className="stat-label">Total Captures</span>
										<span className="stat-value highlight">
											{board.captures}
										</span>
									</div>
								</div>

								<div className="telemetry-box">
									<div className="telemetry-row">
										<span>Current State:</span>
										<span
											className={`telemetry-val ${getStatusClass(board.status)}`}
										>
											{board.status}
										</span>
									</div>
									<div className="telemetry-row">
										<span>Capture Latency:</span>
										<span className="telemetry-val">
											{board.lastLatencyMs ? `${board.lastLatencyMs}ms` : "—"}
										</span>
									</div>
									<div className="telemetry-row">
										<span>Last Payload:</span>
										<span className="telemetry-val">
											{board.lastImageSize
												? `${(board.lastImageSize / 1024).toFixed(1)} KB`
												: "—"}
										</span>
									</div>
									<div className="telemetry-row">
										<span>Last Seen:</span>
										<span className="telemetry-val">
											{board.lastSeen
												? `${Math.floor((Date.now() - board.lastSeen) / 1000)}s ago`
												: "Never"}
										</span>
									</div>
								</div>

								<div className="board-actions">
									<Link
										href={`/board/${board.id}`}
										className="btn btn-primary btn-explore"
									>
										Manage Board Node <span className="arrow">→</span>
									</Link>
								</div>
							</div>
						))
					)}
				</div>
			</section>
		</div>
	);
}
