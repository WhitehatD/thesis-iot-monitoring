"use client";

import mqtt from "mqtt";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useRef, useState } from "react";
import AgentChat from "../../components/AgentChat";

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
	date: string;
	timestamp: number;
	isNew: boolean;
	analysis?: {
		objective: string;
		objectiveMet: boolean;
		description: string;
		findings: string;
		recommendation: string;
		model: string;
		inferenceMs: number;
	};
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
	const [selectedImage, setSelectedImage] = useState<ImageCapture | null>(null);
	const [filterDate, setFilterDate] = useState("all");
	const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
	const [searchTaskId, setSearchTaskId] = useState("");
	const mqttClientRef = useRef<mqtt.MqttClient | null>(null);

	const apiBase = process.env.NEXT_PUBLIC_API_URL || "";

	const mqttUrl =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_MQTT_WS_URL ||
				`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/mqtt`
			: "ws://localhost:9001";

	const fetchImages = useCallback(() => {
		fetch(`${apiBase}/api/images?board_id=${boardId}`)
			.then((res) => res.json())
			.then((data) => {
				if (data.images) {
					setImages(
						data.images.map((img: any) => ({
							taskId: img.task_id,
							filename: img.filename,
							url: `${apiBase}${img.url}`,
							date: img.date,
							timestamp: img.timestamp,
							isNew: false,
						})),
					);
				}
			})
			.catch(console.error);
	}, [apiBase, boardId]);

	useEffect(() => {
		fetchImages();

		// Setup MQTT
		const client = mqtt.connect(mqttUrl, { reconnectPeriod: 3000 });
		mqttClientRef.current = client;

		client.on("connect", () => {
			setGlobalStatus("connected");
			// Subscribe specifically to this board's topics
			client.subscribe(`device/${boardId}/status`, { qos: 0 });
			client.subscribe("device/stm32/status", { qos: 0 }); // Fallback
			client.subscribe("dashboard/images/new", { qos: 0 });
			client.subscribe("dashboard/analysis/new", { qos: 0 });
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

				if (topic === "dashboard/images/new") {
					fetchImages();
					return;
				}

				if (topic === "dashboard/analysis/new") {
					// Attach analysis result to the matching image
					setImages((prev) =>
						prev.map((img) =>
							img.filename === data.filename
								? {
										...img,
										analysis: {
											objective: data.objective || "",
											objectiveMet: data.objective_met || false,
											description: data.description || "",
											findings: data.findings || "",
											recommendation: data.recommendation || "",
											model: data.model || "",
											inferenceMs: data.inference_ms || 0,
										},
									}
								: img,
						),
					);

					const logEntry = {
						time: new Date().toLocaleTimeString(),
						level: "info",
						text: `AI analysis complete for task #${data.task_id}: ${data.objective_met ? "Objective MET" : "Objective NOT met"}`,
					};
					setBoard((prev) => ({
						...prev,
						logs: [logEntry, ...prev.logs].slice(0, 500),
					}));
					return;
				}

				// Global topic checks are done, now enforce source board filtering for board-specific telemetry
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
	}, [mqttUrl, boardId, fetchImages]);

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

	const triggerSetupMode = async () => {
		if (
			!confirm(
				"This will permanently erase the board's WiFi credentials and force it into setup mode. The device will reboot and broadcast its 'IoT-Setup' network. Are you sure?",
			)
		)
			return;
		try {
			await fetch(`${apiBase}/api/erase-wifi`, {
				method: "POST",
				body: JSON.stringify({ board_id: boardId }),
			});
			const logEntry = {
				time: new Date().toLocaleTimeString(),
				level: "warning",
				text: `⚠️ Setup mode triggered for node ${boardId} (WiFi erased)`,
			};
			setBoard((prev) => ({
				...prev,
				logs: [logEntry, ...prev.logs].slice(0, 500),
			}));
		} catch (err) {
			console.error("Trigger setup failed:", err);
		}
	};

	const capturePicture = async () => {
		try {
			await fetch(`${apiBase}/api/capture`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
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

	const deleteImage = async (img: any) => {
		if (!confirm("Are you sure you want to delete this capture?")) return;
		try {
			await fetch(`${apiBase}/api/images/${img.date}/${img.filename}`, {
				method: "DELETE",
			});
			setImages((prev) => prev.filter((i) => i.filename !== img.filename));
			setSelectedImage(null);
		} catch (err) {
			console.error("Delete failed:", err);
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
						<button
							className="btn btn-danger"
							onClick={triggerSetupMode}
							disabled={!board.isOnline}
							style={{
								backgroundColor: "#ff5555",
								borderColor: "#ff3333",
								color: "white",
							}}
						>
							⚠️ Setup Mode
						</button>
					</div>

					<AgentChat boardId={boardId} apiBase={apiBase} />

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
					<div className="gallery-header">
						<h2>Capture History</h2>
						<div className="filter-controls">
							<div className="filter-group">
								<label className="filter-label" htmlFor="filter-date">
									Date
								</label>
								<select
									id="filter-date"
									className="filter-select"
									value={filterDate}
									onChange={(e) => setFilterDate(e.target.value)}
								>
									<option value="all">All Dates</option>
									{[...new Set(images.map((img) => img.date))]
										.sort()
										.reverse()
										.map((date) => (
											<option key={date} value={date}>
												{date}
											</option>
										))}
								</select>
							</div>
							<div className="filter-group">
								<label className="filter-label" htmlFor="filter-sort">
									Sort
								</label>
								<select
									id="filter-sort"
									className="filter-select"
									value={sortOrder}
									onChange={(e) =>
										setSortOrder(e.target.value as "newest" | "oldest")
									}
								>
									<option value="newest">Newest First</option>
									<option value="oldest">Oldest First</option>
								</select>
							</div>
							<div className="filter-group">
								<label className="filter-label" htmlFor="filter-taskId">
									Task ID
								</label>
								<input
									id="filter-taskId"
									type="text"
									className="filter-input"
									placeholder="e.g. 5"
									value={searchTaskId}
									onChange={(e) => setSearchTaskId(e.target.value)}
								/>
							</div>
						</div>
					</div>
					<div className="gallery-grid">
						{(() => {
							let filtered = images;
							if (filterDate !== "all")
								filtered = filtered.filter((img) => img.date === filterDate);
							if (searchTaskId.trim())
								filtered = filtered.filter(
									(img) => String(img.taskId) === searchTaskId.trim(),
								);
							filtered = [...filtered].sort((a, b) =>
								sortOrder === "newest"
									? b.timestamp - a.timestamp
									: a.timestamp - b.timestamp,
							);
							if (filtered.length === 0)
								return (
									<div className="empty-state" style={{ gridColumn: "1 / -1" }}>
										{images.length === 0
											? "No captures received yet."
											: "No captures match the current filters."}
									</div>
								);
							return filtered.map((img) => (
								<div
									key={img.filename}
									className="image-card"
									onClick={() => setSelectedImage(img)}
								>
									{img.isNew && <div className="badge-new">NEW</div>}
									{img.analysis && (
										<div
											className={`analysis-indicator ${img.analysis.objectiveMet ? "met" : "unmet"}`}
											title={
												img.analysis.objectiveMet
													? "Objective met"
													: "Objective not met"
											}
										/>
									)}
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
									<button
										className="btn-delete"
										onClick={(e) => {
											e.stopPropagation();
											deleteImage(img);
										}}
										title="Delete Image"
									>
										🗑️
									</button>
								</div>
							));
						})()}
					</div>
				</section>
			</main>

			{/* Zoom Lightbox Overlay */}
			{selectedImage && (
				<div
					className="lightbox-overlay"
					onClick={() => setSelectedImage(null)}
				>
					<div
						className="lightbox-content"
						onClick={(e) => e.stopPropagation()}
					>
						<button
							className="lightbox-close"
							onClick={() => setSelectedImage(null)}
						>
							✕
						</button>
						<img
							src={selectedImage.url}
							alt="Full Size Export"
							className="lightbox-image"
						/>
						<div className="lightbox-footer">
							<div>
								<h3>Task #{selectedImage.taskId}</h3>
								<p>
									{new Date(selectedImage.timestamp * 1000).toLocaleString()}
								</p>
							</div>
							<div className="lightbox-actions">
								<a
									href={selectedImage.url}
									download
									className="btn btn-secondary"
								>
									Download HD
								</a>
								<button
									className="btn btn-danger"
									onClick={() => deleteImage(selectedImage)}
								>
									Delete Permanently
								</button>
							</div>
						</div>
						{selectedImage.analysis && (
							<div className="analysis-panel">
								<div className="analysis-header">
									<span
										className={`analysis-badge ${selectedImage.analysis.objectiveMet ? "badge-met" : "badge-unmet"}`}
									>
										{selectedImage.analysis.objectiveMet
											? "Objective Met"
											: "Objective Not Met"}
									</span>
									<span className="analysis-meta">
										{selectedImage.analysis.model} &middot;{" "}
										{selectedImage.analysis.inferenceMs.toFixed(0)}ms
									</span>
								</div>
								{selectedImage.analysis.objective && (
									<div className="analysis-row">
										<span className="analysis-label">Objective</span>
										<p>{selectedImage.analysis.objective}</p>
									</div>
								)}
								<div className="analysis-row">
									<span className="analysis-label">Findings</span>
									<p>{selectedImage.analysis.findings}</p>
								</div>
								<div className="analysis-row">
									<span className="analysis-label">Recommendation</span>
									<p>{selectedImage.analysis.recommendation}</p>
								</div>
							</div>
						)}
					</div>
				</div>
			)}
		</div>
	);
}
