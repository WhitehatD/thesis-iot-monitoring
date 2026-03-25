"use client";

import mqtt from "mqtt";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useRef, useState } from "react";

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
	logs: { time: string; level: string; text: string }[];
}

interface ImageCapture {
	taskId: number;
	filename: string;
	url: string;
	timestamp: number;
	isNew: boolean;
}

export default function BoardPage({
	params,
}: {
	params: Promise<{ id: string }>;
}) {
	const unwrappedParams = use(params);
	const boardId = unwrappedParams.id;
	const router = useRouter();

	const [board, setBoard] = useState<BoardTelemetry>({
		id: boardId,
		name: `STM32 B-U585I-IOT02A`,
		firmware: null,
		lastSeen: null,
		status: "idle",
		captures: 0,
		lastImageSize: null,
		lastLatencyMs: null,
		isOnline: true,
		logs: [],
	});

	const [images, setImages] = useState<ImageCapture[]>([]);
	const [globalStatus, setGlobalStatus] = useState("connecting");
	const [scheduleInput, setScheduleInput] = useState("");
	const [isScheduling, setIsScheduling] = useState(false);
	const mqttClientRef = useRef<mqtt.MqttClient | null>(null);

	const apiBase = process.env.NEXT_PUBLIC_API_URL || "";

	const mqttUrl =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_MQTT_WS_URL ||
				`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/mqtt`
			: "ws://localhost:9001";

	useEffect(() => {
		// Fetch initial images for this board (if backend supports filtering, assuming it returns all for now and we filter)
		fetch(`${apiBase}/api/images?board_id=${boardId}`) // Or we filter client side if backend doesn't filter
			.then((res) => res.json())
			.then((data) => {
				if (data.images) {
					// We only show images for this board if possible. Currently the backend /api/images might return all.
					// We'll map them. In a real scenario we'd filter `img.board_id === boardId`.
					setImages(
						data.images.map((img: any) => ({
							taskId: img.task_id,
							filename: img.filename,
							url: `${apiBase}${img.url}`,
							timestamp: img.timestamp,
							isNew: false,
						})),
					);
				}
			})
			.catch(console.error);

		// Setup MQTT
		const client = mqtt.connect(mqttUrl, { reconnectPeriod: 3000 });
		mqttClientRef.current = client;

		client.on("connect", () => {
			setGlobalStatus("connected");
			// Subscribe specifically to this board's topics
			client.subscribe(`device/${boardId}/status`, { qos: 0 });
			client.subscribe("device/stm32/status", { qos: 0 }); // Fallback
			client.subscribe("dashboard/images/new", { qos: 0 });
			client.subscribe("dashboard/logs", { qos: 0 });
		});

		client.on("message", (topic, payload) => {
			try {
				const data = JSON.parse(payload.toString());

				// Identify source board
				let sourceBoardId = "stm32-iot-cam-01";
				if (topic.startsWith("device/")) {
					const parts = topic.split("/");
					if (parts.length >= 3 && parts[1] !== "stm32") {
						sourceBoardId = parts[1];
					}
				}
				if (data.client_id || data.board_id) {
					sourceBoardId = data.client_id || data.board_id;
				}

				// Only process messages for THIS board
				if (sourceBoardId !== boardId) return;

				if (topic === "dashboard/logs") {
					const logTime = data.timestamp
						? new Date(data.timestamp * 1000).toLocaleTimeString()
						: new Date().toLocaleTimeString();
					const logEntry = {
						time: logTime,
						level: data.level || "log",
						text: data.text,
					};
					setBoard((prev) => ({
						...prev,
						logs: [logEntry, ...prev.logs].slice(0, 500),
					}));
					return;
				}

				if (topic === "dashboard/images/new") {
					const newImg: ImageCapture = {
						taskId: data.task_id,
						filename: data.filename,
						url: `${apiBase}${data.url}`,
						timestamp: data.timestamp || Date.now() / 1000,
						isNew: true,
					};
					setImages((prev) => [newImg, ...prev]);

					// Remove popup animation class after 3s
					setTimeout(() => {
						setImages((prev) =>
							prev.map((i) =>
								i.taskId === newImg.taskId ? { ...i, isNew: false } : i,
							),
						);
					}, 3000);
					return;
				}

				setBoard((prev) => {
					const update = { ...prev, isOnline: true, lastSeen: Date.now() };

					if (data.firmware) update.firmware = data.firmware;
					if (data.status) {
						update.status = data.status;
						const logEntry = {
							time: new Date().toLocaleTimeString(),
							level: "info",
							text: `Status transition: ${data.status}`,
						};
						update.logs = [logEntry, ...update.logs].slice(0, 500);
					}
					if (data.status === "captured" || data.status === "uploaded") {
						update.captures += 1;
						if (data.size) update.lastImageSize = data.size;
						if (data.latency_ms) update.lastLatencyMs = data.latency_ms;
					}

					return update;
				});
			} catch (e) {
				console.error("MQTT parse err", e);
			}
		});

		client.on("close", () => setGlobalStatus("disconnected"));
		client.on("error", () => setGlobalStatus("error"));

		// Online checker interval
		const interval = setInterval(() => {
			setBoard((prev) => {
				const now = Date.now();
				if (prev.isOnline && prev.lastSeen && now - prev.lastSeen > 15000) {
					return { ...prev, isOnline: false };
				}
				return prev;
			});
		}, 5000);

		return () => {
			client.end();
			clearInterval(interval);
		};
	}, [apiBase, mqttUrl, boardId]);

	const pingBoard = async () => {
		try {
			await fetch(`${apiBase}/api/ping`, {
				method: "POST",
				body: JSON.stringify({ board_id: boardId }),
			});
			const logEntry = {
				time: new Date().toLocaleTimeString(),
				level: "info",
				text: `📡 Ping command sent to node ${boardId}`,
			};
			setBoard((prev) => ({
				...prev,
				logs: [logEntry, ...prev.logs].slice(0, 500),
			}));
		} catch (err) {
			console.error("Ping failed:", err);
		}
	};

	const capturePicture = async () => {
		try {
			await fetch(`${apiBase}/api/capture`, {
				method: "POST",
				body: JSON.stringify({ board_id: boardId }),
			});
			const logEntry = {
				time: new Date().toLocaleTimeString(),
				level: "info",
				text: `📸 Capture triggered for node ${boardId}`,
			};
			setBoard((prev) => ({
				...prev,
				logs: [logEntry, ...prev.logs].slice(0, 500),
			}));
		} catch (err) {
			console.error("Capture failed:", err);
		}
	};

	const createSchedule = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!scheduleInput.trim()) return;

		setIsScheduling(true);
		try {
			// Submitting natural language prompt to AI scheduler
			await fetch(`${apiBase}/api/plan`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ prompt: scheduleInput, board_id: boardId }),
			});

			const logEntry = {
				time: new Date().toLocaleTimeString(),
				level: "info",
				text: `📅 Schedule created: "${scheduleInput}"`,
			};
			setBoard((prev) => ({
				...prev,
				logs: [logEntry, ...prev.logs].slice(0, 500),
			}));
			setScheduleInput("");
		} catch (err) {
			console.error("Schedule failed:", err);
		} finally {
			setIsScheduling(false);
		}
	};

	const clearLogs = () => {
		setBoard((prev) => ({ ...prev, logs: [] }));
	};

	const getStatusClass = (status: string) => {
		if (status.includes("error") || status.includes("failed"))
			return "status-error";
		if (status.includes("captur") || status.includes("upload"))
			return "status-active";
		if (status.includes("ota") || status.includes("ping")) return "status-ota";
		return "status-idle";
	};

	return (
		<div className="app-container split-layout">
			<header className="header full-width">
				<div className="header-title-container">
					<button onClick={() => router.push("/")} className="btn-back">
						← Back
					</button>
					<div>
						<h1 className="header-title">{board.name}</h1>
						<div className="header-subtitle">Node: {boardId}</div>
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

			<aside className="sidebar">
				<div className="board-card glass-panel no-hover">
					<div className="board-header">
						<div className="board-name-group">
							<div className="board-icon">⚡</div>
							<span style={{ fontWeight: 600 }}>Telemetry</span>
						</div>
						<div
							className={`status-indicator ${board.isOnline ? "online" : "offline"}`}
						>
							<div className="dot" />
							{board.isOnline ? "Online" : "Offline"}
						</div>
					</div>

					<div className="telemetry-box mt-4">
						<div className="telemetry-row">
							<span>Current State:</span>
							<span className={`telemetry-val ${getStatusClass(board.status)}`}>
								{board.status}
							</span>
						</div>
						<div className="telemetry-row">
							<span>Firmware:</span>
							<span className="telemetry-val">{board.firmware || "—"}</span>
						</div>
						<div className="telemetry-row">
							<span>Total Captures:</span>
							<span className="telemetry-val highlight">{board.captures}</span>
						</div>
						<div className="telemetry-row">
							<span>Last Payload:</span>
							<span className="telemetry-val">
								{board.lastImageSize
									? `${(board.lastImageSize / 1024).toFixed(1)} KB`
									: "—"}
							</span>
						</div>
					</div>

					<div className="board-actions column-actions">
						<button
							className="btn btn-primary"
							onClick={capturePicture}
							disabled={!board.isOnline}
						>
							📸 Capture Picture
						</button>
						<button
							className="btn"
							onClick={pingBoard}
							disabled={!board.isOnline}
						>
							📡 Ping Node
						</button>
					</div>

					<div className="schedule-section mt-4">
						<div className="section-title">Create Schedule</div>
						<form onSubmit={createSchedule} className="schedule-form">
							<input
								type="text"
								placeholder="e.g. 'Take a picture every 5 seconds for 1 min'"
								value={scheduleInput}
								onChange={(e) => setScheduleInput(e.target.value)}
								className="schedule-input"
								disabled={!board.isOnline || isScheduling}
							/>
							<button
								type="submit"
								className="btn btn-secondary"
								disabled={
									!board.isOnline || isScheduling || !scheduleInput.trim()
								}
							>
								{isScheduling ? "Generating..." : "Apply"}
							</button>
						</form>
					</div>

					<div className="terminal-window">
						<div className="terminal-header">
							<span>Board Console</span>
							<button className="btn-text" onClick={clearLogs}>
								Clear
							</button>
						</div>
						{board.logs.length === 0 ? (
							<div className="terminal-empty">No telemetry received yet...</div>
						) : (
							board.logs.map((log, idx) => (
								<div key={idx} className={`log-line log-${log.level}`}>
									<span className="log-time">[{log.time}]</span>
									{log.text}
								</div>
							))
						)}
					</div>
				</div>
			</aside>

			<main className="main-content">
				<section className="images-section">
					<h2>Capture History</h2>
					<div className="gallery-grid">
						{images.length === 0 ? (
							<div className="empty-state" style={{ gridColumn: "1 / -1" }}>
								No captures received yet.
							</div>
						) : (
							images.map((img) => (
								<div key={img.taskId} className="image-card">
									{img.isNew && <div className="badge-new">NEW</div>}
									<div className="image-wrapper">
										<img
											src={img.url}
											alt={`Capture ${img.taskId}`}
											loading="lazy"
										/>
									</div>
									<div className="image-meta">
										<span>Task #{img.taskId}</span>
										<span className="image-time">
											{new Date(img.timestamp * 1000).toLocaleTimeString()}
										</span>
									</div>
								</div>
							))
						)}
					</div>
				</section>
			</main>
		</div>
	);
}
