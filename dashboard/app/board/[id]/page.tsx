"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
import AgentChat from "../../components/AgentChat";
import { useMQTT } from "../../hooks/useMQTT";

type ConnectionState = "online" | "sleeping" | "offline";

interface BoardState {
	firmware: string | null;
	lastSeen: number | null;
	status: string;
	captures: number;
	lastImageSize: number | null;
	lastLatencyMs: number | null;
	connection: ConnectionState;
	logs: LogEntry[];
}

interface LogEntry {
	id: number;
	time: string;
	level:
		| "info"
		| "success"
		| "warning"
		| "error"
		| "mqtt"
		| "camera"
		| "upload"
		| "ota"
		| "system";
	tag: string;
	text: string;
	meta?: string;
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

const MAX_LOGS = 500;

export default function BoardPage({
	params,
}: {
	params: Promise<{ id: string }>;
}) {
	const { id: boardId } = use(params);
	const apiBase = process.env.NEXT_PUBLIC_API_URL || "";

	const [board, setBoard] = useState<BoardState>({
		firmware: null,
		lastSeen: null,
		status: "idle",
		captures: 0,
		lastImageSize: null,
		lastLatencyMs: null,
		connection: "sleeping",
		logs: [],
	});
	const [images, setImages] = useState<ImageCapture[]>([]);
	const [selectedImage, setSelectedImage] = useState<ImageCapture | null>(null);
	const [activeTab, setActiveTab] = useState<"gallery" | "schedules">(
		"gallery",
	);
	const [schedules, setSchedules] = useState<any[]>([]);
	const [actionLoading, setActionLoading] = useState<string | null>(null);

	const logIdRef = useRef(0);
	const addLog = useCallback(
		(level: LogEntry["level"], tag: string, text: string, meta?: string) => {
			logIdRef.current += 1;
			const entry: LogEntry = {
				id: logIdRef.current,
				time: new Date().toLocaleTimeString("en-GB", {
					hour: "2-digit",
					minute: "2-digit",
					second: "2-digit",
				}),
				level,
				tag,
				text,
				meta,
			};
			setBoard((prev) => ({
				...prev,
				logs: [entry, ...prev.logs].slice(0, MAX_LOGS),
			}));
		},
		[],
	);

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

	const fetchSchedules = useCallback(() => {
		fetch(`${apiBase}/api/schedules`)
			.then((r) => r.json())
			.then((data) => setSchedules(data.schedules ?? data ?? []))
			.catch(() => {});
	}, [apiBase]);

	useEffect(() => {
		fetchImages();
		fetchSchedules();
	}, [fetchImages, fetchSchedules]);

	// Poll schedules as fallback (MQTT push is primary, poll catches missed updates)
	useEffect(() => {
		const interval = setInterval(fetchSchedules, 5000);
		return () => clearInterval(interval);
	}, [fetchSchedules]);

	const handleMessage = useCallback(
		(topic: string, data: Record<string, any>, sourceBoardId: string) => {
			// Dashboard image notification
			if (topic === "dashboard/images/new") {
				fetchImages();
				fetchSchedules();
				addLog(
					"upload",
					"IMG",
					`New image: ${data.filename}`,
					`task #${data.task_id}`,
				);
				return;
			}

			// AI analysis result
			if (topic === "dashboard/analysis/new") {
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
				const met = data.objective_met;
				addLog(
					met ? "success" : "warning",
					"AI",
					`Vision analysis: ${met ? "objective met" : "objective not met"}`,
					`${data.model || "?"} · ${data.inference_ms || 0}ms · task #${data.task_id}`,
				);
				return;
			}

			// Real-time schedule/task updates
			if (topic === "dashboard/schedules/updated") {
				if (data.schedules) {
					setSchedules(data.schedules);
					addLog(
						"mqtt",
						"SCHED",
						`Schedule update via MQTT (${data.schedules.length} schedules)`,
					);
				}
				return;
			}

			// Board firmware logs (raw text from MQTT)
			if (topic === `device/${boardId}/logs`) {
				const raw: string = data.raw || data.message || "";
				const parsed = parseFirmwareLog(raw);
				addLog(parsed.level, parsed.tag, parsed.text, parsed.meta);
				return;
			}

			// Server-side logs
			if (topic === "dashboard/logs") {
				addLog(
					"system",
					"SRV",
					data.text || "Server log",
					data.level || undefined,
				);
				return;
			}

			// Board telemetry — filter by board ID
			if (sourceBoardId !== boardId) return;

			setBoard((prev) => {
				const update = {
					...prev,
					connection: "online" as ConnectionState,
					lastSeen: Date.now(),
				};
				if (data.firmware) update.firmware = data.firmware;
				if (data.status) update.status = data.status;
				if (data.status === "captured" || data.status === "uploaded") {
					update.captures += 1;
					if (data.size) update.lastImageSize = data.size;
					if (data.latency_ms) update.lastLatencyMs = data.latency_ms;
				}
				// Board going to sleep
				if (data.status === "sleep" || data.status === "cycle_complete") {
					update.connection = "sleeping";
				}
				return update;
			});

			// Produce detailed log from board status
			const status = data.status;
			if (!status) {
				// Heartbeat without status change
				addLog(
					"mqtt",
					"HB",
					"Heartbeat received",
					data.firmware ? `fw ${data.firmware}` : undefined,
				);
				return;
			}

			const taskMeta = data.task_id ? `task #${data.task_id}` : undefined;

			switch (status) {
				case "idle":
					addLog("info", "BOARD", "Board idle — awaiting commands");
					break;
				case "executing":
					addLog("info", "SCHED", `Executing scheduled task`, taskMeta);
					break;
				case "camera_init":
					addLog(
						"camera",
						"CAM",
						"Camera cold start — initializing sensor",
						taskMeta,
					);
					break;
				case "capturing":
					addLog("camera", "CAM", "Capturing frame (VGA RGB565)", taskMeta);
					break;
				case "captured":
					addLog(
						"success",
						"CAM",
						`Frame captured — ${data.size ? `${(data.size / 1024).toFixed(0)} KB` : "?"}`,
						taskMeta,
					);
					break;
				case "uploading":
					addLog("upload", "HTTP", "Uploading image to server...", taskMeta);
					break;
				case "uploaded":
					addLog(
						"success",
						"HTTP",
						`Upload complete — ${data.bytes ? `${(data.bytes / 1024).toFixed(0)} KB` : "OK"}`,
						data.latency_ms ? `${data.latency_ms}ms` : taskMeta,
					);
					break;
				case "cycle_complete":
					addLog("success", "SCHED", "All scheduled tasks completed for today");
					break;
				case "ota_checking":
					addLog("ota", "OTA", "Checking for firmware update...");
					break;
				case "ota_downloading":
					addLog(
						"ota",
						"OTA",
						`Downloading firmware v${data.version || "?"}`,
						data.progress ? `${data.progress}%` : undefined,
					);
					break;
				case "ota_complete":
					addLog(
						"success",
						"OTA",
						`OTA complete — rebooting to v${data.version || "?"}`,
					);
					break;
				case "sleep":
					addLog(
						"system",
						"PWR",
						"Entering STOP2 sleep mode",
						data.wake_time || undefined,
					);
					break;
				case "wake":
					addLog("system", "PWR", "Woke from sleep — reconnecting");
					break;
				default:
					if (status.includes("error") || status.includes("fail")) {
						addLog("error", "ERR", `${status}`, data.reason || taskMeta);
					} else {
						addLog("info", "BOARD", status, taskMeta);
					}
			}
		},
		[boardId, fetchImages, fetchSchedules, addLog],
	);

	const topics = [
		`device/${boardId}/status`,
		`device/${boardId}/logs`,
		"dashboard/images/new",
		"dashboard/analysis/new",
		"dashboard/logs",
		"dashboard/schedules/updated",
	];
	const { connectionStatus } = useMQTT(topics, handleMessage);

	// Transition: online → sleeping (15s) → offline (2min)
	useEffect(() => {
		const interval = setInterval(() => {
			setBoard((prev) => {
				if (!prev.lastSeen) return prev;
				const elapsed = Date.now() - prev.lastSeen;
				if (prev.connection === "online" && elapsed > 15000) {
					return { ...prev, connection: "sleeping" };
				}
				if (prev.connection === "sleeping" && elapsed > 120000) {
					return { ...prev, connection: "offline" };
				}
				return prev;
			});
		}, 5000);
		return () => clearInterval(interval);
	}, []);

	// Close lightbox on Escape
	useEffect(() => {
		const handleEsc = (e: KeyboardEvent) => {
			if (e.key === "Escape") setSelectedImage(null);
		};
		window.addEventListener("keydown", handleEsc);
		return () => window.removeEventListener("keydown", handleEsc);
	}, []);

	const deleteImage = async (img: ImageCapture) => {
		if (!confirm("Delete this capture permanently?")) return;
		try {
			await fetch(`${apiBase}/api/images/${img.date}/${img.filename}`, {
				method: "DELETE",
			});
			setImages((prev) => prev.filter((i) => i.filename !== img.filename));
			setSelectedImage(null);
		} catch (err) {
			addLog("error", "HTTP", `Delete failed: ${err}`);
		}
	};

	const handleCapture = async () => {
		setActionLoading("capture");
		addLog("info", "CMD", "Sending capture command...");
		try {
			const res = await fetch(`${apiBase}/api/capture`, { method: "POST" });
			const data = await res.json();
			addLog("success", "CMD", "Capture command sent", `task #${data.task_id}`);
		} catch (err) {
			addLog("error", "CMD", `Capture failed: ${err}`);
		} finally {
			setActionLoading(null);
		}
	};

	const handlePing = async () => {
		setActionLoading("ping");
		addLog("info", "CMD", "Sending ping to board...");
		try {
			await fetch(`${apiBase}/api/ping`, { method: "POST" });
			addLog("success", "CMD", "Ping sent — LED sequence triggered");
		} catch (err) {
			addLog("error", "CMD", `Ping failed: ${err}`);
		} finally {
			setActionLoading(null);
		}
	};

	const handleSetup = async () => {
		setActionLoading("setup");
		addLog("warning", "CMD", "Entering WiFi setup mode...");
		try {
			await fetch(`${apiBase}/api/erase-wifi`, { method: "POST" });
			addLog(
				"success",
				"CMD",
				"Setup mode activated — board starting AP at 192.168.10.1",
			);
		} catch (err) {
			addLog("error", "CMD", `Setup mode failed: ${err}`);
		} finally {
			setActionLoading(null);
		}
	};

	const handleRefresh = () => {
		addLog("info", "CMD", "Refreshing images & schedules...");
		fetchImages();
		fetchSchedules();
	};

	const sortedImages = [...images].sort((a, b) => b.timestamp - a.timestamp);

	return (
		<div className="app-container agent-layout">
			{/* Header */}
			<header className="agent-header-bar">
				<div className="agent-header-left">
					<Link href="/" className="btn-back">
						&larr;
					</Link>
					<h1 className="agent-header-title">Monitoring Agent</h1>
					<span className="agent-header-node">{boardId}</span>
				</div>
				<div className="agent-header-actions">
					<button
						className="btn-action accent"
						onClick={handleCapture}
						disabled={actionLoading !== null}
					>
						{actionLoading === "capture" ? "Sending..." : "Capture"}
					</button>
					<button
						className="btn-action"
						onClick={handlePing}
						disabled={actionLoading !== null}
					>
						{actionLoading === "ping" ? "Sending..." : "Ping"}
					</button>
					<button
						className="btn-action"
						onClick={handleSetup}
						disabled={actionLoading !== null}
					>
						{actionLoading === "setup" ? "Sending..." : "Setup"}
					</button>
					<button className="btn-action" onClick={handleRefresh}>
						Refresh
					</button>
				</div>
				<div className="agent-header-stats">
					<div className={`status-indicator ${board.connection}`}>
						<div className="dot" />
						{board.connection === "online"
							? "Online"
							: board.connection === "sleeping"
								? "Standby"
								: "Offline"}
					</div>
					<span className="header-chip">
						FW {board.firmware ? `v${board.firmware}` : "\u2014"}
					</span>
					<span className="header-chip">
						<span className={getStatusClass(board.status)}>{board.status}</span>
					</span>
					<span className="header-chip highlight">{board.captures} caps</span>
					<div className="connection-badge">
						<div
							className={`connection-dot ${connectionStatus === "connected" ? "connected" : "disconnected"}`}
						/>
						MQTT
					</div>
				</div>
			</header>

			{/* Left: Agent Chat */}
			<main className="agent-main">
				<AgentChat boardId={boardId} apiBase={apiBase} fullSize />
			</main>

			{/* Right: Gallery/Schedules (top) + Console (bottom, always visible) */}
			<aside className="agent-panel">
				<div className="panel-upper">
					<div className="panel-tabs">
						<button
							className={`panel-tab ${activeTab === "gallery" ? "active" : ""}`}
							onClick={() => setActiveTab("gallery")}
						>
							Gallery
							{images.length > 0 && (
								<span className="tab-count">{images.length}</span>
							)}
						</button>
						<button
							className={`panel-tab ${activeTab === "schedules" ? "active" : ""}`}
							onClick={() => setActiveTab("schedules")}
						>
							Schedules
							{schedules.length > 0 && (
								<span className="tab-count">{schedules.length}</span>
							)}
						</button>
					</div>

					<div className="panel-content">
						{activeTab === "gallery" && (
							<div className="sidebar-gallery">
								{sortedImages.length === 0 ? (
									<div className="empty-state-sm">
										No captures yet. Ask the agent to take a picture.
									</div>
								) : (
									sortedImages.map((img) => (
										<div
											key={img.filename}
											className="sidebar-image-card"
											onClick={() => setSelectedImage(img)}
										>
											{img.analysis && (
												<div
													className={`analysis-indicator ${img.analysis.objectiveMet ? "met" : "unmet"}`}
												/>
											)}
											<div className="sidebar-image-wrapper">
												<img
													src={img.url}
													alt={`Task ${img.taskId}`}
													loading="lazy"
												/>
											</div>
											<div className="sidebar-image-meta">
												<span>#{img.taskId}</span>
												<span className="image-time">
													{new Date(img.timestamp * 1000).toLocaleTimeString()}
												</span>
											</div>
										</div>
									))
								)}
							</div>
						)}

						{activeTab === "schedules" && (
							<div className="schedules-list">
								{schedules.length === 0 ? (
									<div className="empty-state-sm">
										No schedules yet. Ask the agent to create one.
									</div>
								) : (
									schedules.map((sched: any) => {
										const tasks = sched.tasks || [];
										const done = tasks.filter(
											(t: any) => t.completed_at,
										).length;
										const allDone = tasks.length > 0 && done === tasks.length;
										return (
											<div
												key={sched.id}
												className={`schedule-card ${sched.is_active ? "active" : ""} ${allDone ? "completed" : ""}`}
											>
												<div className="schedule-header">
													<span className="schedule-name">{sched.name}</span>
													{allDone ? (
														<span className="schedule-badge done">
															Completed
														</span>
													) : sched.is_active ? (
														<span className="schedule-badge">Active</span>
													) : (
														<span className="schedule-badge inactive">
															Inactive
														</span>
													)}
												</div>
												<div className="schedule-progress">
													<div
														className="schedule-progress-bar"
														style={{
															width: tasks.length
																? `${(done / tasks.length) * 100}%`
																: "0%",
														}}
													/>
												</div>
												<div className="schedule-tasks">
													{tasks.map((task: any) => (
														<div
															key={task.id}
															className={`schedule-task ${task.completed_at ? "task-done" : ""}`}
														>
															<span className="schedule-check">
																{task.completed_at ? "\u2713" : "\u25CB"}
															</span>
															<span className="schedule-time">{task.time}</span>
															<span className="schedule-obj">
																{task.objective || task.action}
															</span>
														</div>
													))}
												</div>
											</div>
										);
									})
								)}
							</div>
						)}
					</div>
				</div>

				{/* Console — always visible */}
				<div className="panel-console">
					<div className="console-header">
						<span className="console-title">Console</span>
						<span className="console-count">{board.logs.length}</span>
						<button
							className="btn-text"
							onClick={() => setBoard((prev) => ({ ...prev, logs: [] }))}
						>
							Clear
						</button>
					</div>
					<div className="console-body">
						{board.logs.length === 0 ? (
							<div className="terminal-empty">
								Waiting for board telemetry...
							</div>
						) : (
							board.logs.map((log) => (
								<div key={log.id} className={`log-entry log-${log.level}`}>
									<span className="log-time">{log.time}</span>
									<span className="log-tag">{log.tag}</span>
									<span className="log-text">{log.text}</span>
									{log.meta && <span className="log-meta">{log.meta}</span>}
								</div>
							))
						)}
					</div>
				</div>
			</aside>

			{/* Lightbox */}
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
							&times;
						</button>
						<img
							src={selectedImage.url}
							alt="Full size capture"
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
									Download
								</a>
								<button
									className="btn btn-danger"
									onClick={() => deleteImage(selectedImage)}
								>
									Delete
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

const FIRMWARE_LOG_RE = /^\[\s*(\d+)ms\]\s*\[(\w+)\s*\]\s*\[([^\]]+)\]\s*(.*)$/;

const FW_LEVEL_MAP: Record<string, LogEntry["level"]> = {
	DBG: "mqtt",
	INFO: "info",
	OK: "success",
	WARN: "warning",
	ERR: "error",
};

function parseFirmwareLog(raw: string): {
	level: LogEntry["level"];
	tag: string;
	text: string;
	meta?: string;
} {
	const m = FIRMWARE_LOG_RE.exec(raw);
	if (m) {
		const [, ms, level, tag, text] = m;
		return {
			level: FW_LEVEL_MAP[level] || "system",
			tag: tag.substring(0, 5),
			text: text.trim(),
			meta: `${(Number(ms) / 1000).toFixed(1)}s`,
		};
	}
	return { level: "system", tag: "FW", text: raw || "(empty)" };
}

function getStatusClass(status: string): string {
	if (status.includes("error") || status.includes("failed"))
		return "status-error";
	if (status.includes("captur") || status.includes("upload"))
		return "status-active";
	if (status.includes("ota") || status.includes("ping")) return "status-ota";
	return "status-idle";
}
